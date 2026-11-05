import {test} from "node:test";
import assert from "node:assert/strict";
import {TerminalConnection} from "../terminal-connection.js";

function setup(t, factory, url = "wss://portal/terminal", options = {}) {
  t.mock.timers.enable({apis:["setTimeout", "Date"]});
  globalThis.WebSocket = {OPEN:1};
  const sockets = [], statuses = [], errors = [], outputs = [], completions = [], notices = [];
  let ready = 0;
  const makeSocket = factory || (url => {
    const socket = {url,readyState:0, sent:[], close(){this.onclose?.({code:1000});}, send(value){this.sent.push(JSON.parse(value));}};
    sockets.push(socket);
    return socket;
  });
  const connection = new TerminalConnection(url, {
    status:(...value)=>statuses.push(value), error:value=>errors.push(value),
    ready:()=>ready++, output:value=>outputs.push(value), disconnected:()=>{}, complete:code=>completions.push(code),
    notice:message=>notices.push(message),
  }, {makeSocket, random:()=>0, ...options});
  t.after(()=>connection.close());
  return {connection,sockets,statuses,errors,outputs,completions,notices,ready:()=>ready};
}
function control(socket, value) {
  socket.onmessage({data:new TextEncoder().encode(JSON.stringify(value)).buffer});
}

test("hung handshakes retry three times then offer manual retry", t => {
  const {connection,sockets,statuses,errors}=setup(t);
  for(let attempt=0;attempt<4;attempt++) {
    t.mock.timers.tick(25000);
    if(attempt<3) {
      assert.equal(statuses.at(-1)[0],`Reconnecting ${attempt+1}/3…`);
      t.mock.timers.tick((attempt+1)*1000);
    }
  }
  assert.equal(sockets.length,4);
  assert.deepEqual(statuses.at(-1),["Terminal connection failed after 3 retries.",true]);
  assert.equal(errors.at(-1).code,"client-timeout");
  connection.retry();
  assert.equal(sockets.length,5);
  assert.deepEqual(statuses.at(-1),["Connecting…",false]);
});

test("transport upgrade cannot enable input before the server shell is ready", t => {
  const {connection,sockets,ready}=setup(t);
  const socket=sockets[0];
  socket.readyState=1; socket.onopen();
  connection.send({type:"input",data:"login\n"});
  assert.equal(socket.sent.length,0);
  assert.equal(ready(),0);
  control(socket,{type:"ready"});
  control(socket,{type:"ready"});
  assert.equal(ready(),1);
  connection.send({type:"input",data:"login\n"});
  assert.deepEqual(socket.sent,[{type:"input",data:"login\n"}]);
  t.mock.timers.tick(30000);
  assert.equal(sockets.length,1);
});

test("server errors preserve diagnostics and recovery clears them", t => {
  const {connection,sockets,errors,statuses,outputs}=setup(t);
  const error={type:"error",code:"server-timeout",stage:"exec",message:"Exec timed out",request_id:"id-1"};
  control(sockets[0],error);
  assert.deepEqual(errors.at(-1),error);
  t.mock.timers.tick(1000);
  sockets[0].onmessage({data:"stale output"});
  assert.deepEqual(outputs,[]);
  sockets[1].readyState=1;
  control(sockets[1],{type:"ready"});
  assert.equal(errors.at(-1),null);
  assert.equal(statuses.at(-1)[0],"Reconnected · new shell");
  connection.close();
});

test("closing the connection cancels retries and ignores stale callbacks", t => {
  const {connection,sockets,ready}=setup(t);
  sockets[0].onerror();
  connection.close();
  t.mock.timers.tick(100000);
  control(sockets[0],{type:"ready"});
  assert.equal(sockets.length,1);
  assert.equal(ready(),0);
});

test("a stalled exec distinguishes opening-shell timeout from handshake timeout", t => {
  const {sockets,errors}=setup(t);
  sockets[0].readyState=1; sockets[0].onopen();
  t.mock.timers.tick(25000);
  assert.match(errors.at(-1).message,/waiting for the server to open/);
});

test("socket construction failures and duplicate error/close events do not stack retries", t => {
  const {sockets,statuses}=setup(t);
  sockets[0].onerror(); sockets[0].onclose({code:1006});
  t.mock.timers.tick(1000);
  assert.equal(sockets.length,2);
  assert.equal(statuses.at(-1)[0],"Reconnecting 1/3…");
});

test("helper sessions never automatically rerun after a disconnect", t => {
  const {connection,sockets,statuses}=setup(t);
  connection.maxRetries=0;
  sockets[0].onerror();
  t.mock.timers.tick(100000);
  assert.equal(sockets.length,1);
  assert.deepEqual(statuses.at(-1),["Helper session ended. Open a new session to run it again.",true]);
});

test("helper completion returns to a regular shell while retaining scope and output", t => {
  const {connection,sockets,statuses,errors,outputs,completions}=setup(t,null,"wss://portal/terminal?owner=alice&helper=claude-login");
  connection.maxRetries=0;
  control(sockets[0],{type:"ready"});
  sockets[0].onmessage({data:"Signed in successfully"});
  control(sockets[0],{type:"complete",exit_code:0});
  assert.equal(sockets.length,2);
  assert.equal(connection.shellReady,false);
  assert.equal(connection.url,"wss://portal/terminal?owner=alice");
  assert.equal(sockets[1].url,connection.url);
  assert.deepEqual(completions,[0]);
  assert.deepEqual(outputs,["Signed in successfully"]);
  sockets[1].readyState=1;
  control(sockets[1],{type:"ready"});
  t.mock.timers.tick(100000);
  assert.equal(sockets.length,2);
  assert.equal(connection.shellReady,true);
  assert.deepEqual(statuses.at(-1),["Connected",false]);
  assert.equal(errors.at(-1),null);
});

test("failed helpers return their exit code and shell retries never replay the helper", t => {
  const {connection,sockets,completions}=setup(t,null,"wss://portal/terminal?namespace=team&helper=custom");
  connection.maxRetries=0;
  control(sockets[0],{type:"complete",exit_code:4});
  assert.deepEqual(completions,[4]);
  sockets[1].onerror();
  t.mock.timers.tick(1000);
  assert.equal(sockets.length,3);
  assert.equal(connection.url,"wss://portal/terminal?namespace=team");
  assert.equal(sockets[2].url,connection.url);
  control(sockets[0],{type:"complete",exit_code:0});
  assert.deepEqual(completions,[4]);
});

test("drain warning counts down while input stays available, then reconnects without replay", t => {
  const {connection,sockets,notices,errors}=setup(t);
  const first=sockets[0];
  first.readyState=1;
  control(first,{type:"ready"});
  connection.send({type:"input",data:"echo once\n"});
  control(first,{type:"draining",seconds_remaining:3});
  assert.match(notices.at(-1),/restarting in 3s/);
  t.mock.timers.tick(1000);
  assert.match(notices.at(-1),/restarting in 2s/);
  assert.equal(connection.shellReady,true);
  first.onclose({code:1012});
  assert.equal(errors.at(-1),null);
  t.mock.timers.tick(1000);
  sockets[1].readyState=1;
  control(sockets[1],{type:"ready"});
  assert.equal(notices.at(-1),null);
  assert.deepEqual(sockets[1].sent,[]);
  assert.deepEqual(first.sent,[{type:"input",data:"echo once\n"}]);
});

test("an interrupted helper never reconnects even when callers omit the helper retry setting", t => {
  const {sockets,notices,statuses}=setup(t,null,"wss://portal/terminal?helper=login");
  control(sockets[0],{type:"ready"});
  control(sockets[0],{type:"draining",seconds_remaining:2});
  sockets[0].onclose({code:1012});
  t.mock.timers.tick(100000);
  assert.equal(sockets.length,1);
  assert.match(notices.at(-1),/helper was not rerun/);
  assert.equal(statuses.at(-1)[1],true);
});

test("closing a draining terminal cancels countdowns and reconnect timers", t => {
  const {connection,sockets,notices}=setup(t);
  control(sockets[0],{type:"draining",seconds_remaining:10});
  connection.close();
  const count=notices.length;
  t.mock.timers.tick(100000);
  assert.equal(sockets.length,1);
  assert.equal(notices.length,count);
});

test("reconnect jitter spreads clients while keeping retries bounded", t => {
  const {sockets}=setup(t,null,"wss://portal/terminal",{random:()=>1});
  sockets[0].onclose({code:1006});
  t.mock.timers.tick(1000);
  assert.equal(sockets.length,1);
  t.mock.timers.tick(500);
  assert.equal(sockets.length,2);
});
