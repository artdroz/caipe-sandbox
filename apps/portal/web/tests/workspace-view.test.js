import test from "node:test";
import assert from "node:assert/strict";
import {configurationDiff,fileTemplate,workspacePanel} from "../workspace-view.js";

const data={files:{startup:[{name:"10-work.sh",exists:true,status:"changed",recovery_sources:["applied"]}],service:[{name:"omnigent.conf",exists:true,status:"applied",recovery_sources:["applied","default"]}]},services:[{name:"omnigent",group:"omnigent",statename:"RUNNING",pid:123}],startup:[{name:"10-work.sh",exit_code:0,timed_out:false}],service_errors:[],active_drift:false,runtime_drift:false};
const state={data,kind:"startup",name:"10-work.sh",content:"echo hello",isNew:false,busy:false,dirty:false,message:"",failed:false,log:null,mode:"edit",restore:null,review:null};

test("editor separates file navigation from editing and explains startup limits",()=>{
 const html=workspacePanel({...state,dirty:true});
 assert.match(html,/ws-sidebar/);assert.match(html,/ws-code-editor/);
 assert.match(html,/home across suspend and resume/);assert.match(html,/on sandbox start and resume/);
 assert.match(html,/15-second timeout/);assert.match(html,/60-second budget/);
 assert.match(html,/Unsaved changes/);assert.match(html,/data-workspace-action="save"/);
 assert.match(html,/data-workspace-action="reload-file"/);assert.match(html,/Changed/);
});
test("service state and controls do not claim connection health",()=>{
 const html=workspacePanel({...state,kind:"service",name:"omnigent.conf"});
 assert.match(html,/Process state/);assert.match(html,/Running/);
 for(const action of ["apply","stop","restart","logs"])assert.ok(html.includes(`data-workspace-action="${action}"`));
 assert.doesNotMatch(html,/Connected|Healthy/);
});
test("deleted files remain selectable with restore actions while process state stays visible",()=>{
 const missing={...data,files:{...data.files,service:[{name:"omnigent.conf",exists:false,status:"deleted",recovery_sources:["applied","default"]}]}};
 const html=workspacePanel({...state,data:missing,kind:"service",name:"omnigent.conf"});
 assert.match(html,/Deleted/);assert.match(html,/This file was deleted/);assert.match(html,/Running/);
 assert.match(html,/Restore last applied/);assert.doesNotMatch(html,/<textarea/);
});
test("review lists process effects and requires a separate apply action",()=>{
 const html=workspacePanel({...state,kind:"service",mode:"review",review:{revision:"abc",operations:[{name:"omnigent",action:"remove"},{name:"my-api",action:"start"}],errors:[],repair:true,can_apply:true}});
 assert.match(html,/Stop & remove/);assert.match(html,/my-api/);assert.match(html,/Start/);
 assert.match(html,/Generated configuration is missing/);assert.match(html,/data-workspace-action="confirm-apply"/);
 assert.doesNotMatch(html,/<textarea/);
});
test("saved-version preview shows an escaped diff and an explicit restore action",()=>{
 const html=workspacePanel({...state,mode:"restore",restore:{source:"applied",content:"echo restored\n"}});
 assert.match(html,/RESTORE PREVIEW/);assert.match(html,/ws-diff-added/);assert.match(html,/ws-diff-removed/);
 assert.match(html,/data-workspace-action="confirm-restore"/);
 assert.doesNotMatch(configurationDiff("",'<script>bad</script>'),/<script>/);
});
test("invalid configuration blocks Apply and explains why operations cannot be planned",()=>{
 const html=workspacePanel({...state,kind:"service",mode:"review",review:{operations:[],errors:[{name:"example.conf",error:"Supervisor rejected the service configuration"}],can_apply:false}});
 assert.match(html,/Fix validation errors to review service operations/);
 assert.match(html,/example.conf: Supervisor rejected/);
 assert.match(html,/data-workspace-action="confirm-apply" disabled/);
});
test("restore comparisons stop at a bounded edit length",()=>{
 const before=Array.from({length:3000},(_,i)=>`before-${i}\n`).join("");
 const after=Array.from({length:3000},(_,i)=>`after-${i}\n`).join("");
 assert.match(configurationDiff(before,after),/comparison is too large/);
});
test("file, log and error content is escaped",()=>{
 const html=workspacePanel({...state,name:'"><script>bad</script>',content:'</textarea><script>bad</script>',message:'<img src=x onerror=bad()>'});
 assert.doesNotMatch(html,/<script>|<img/);assert.match(html,/&lt;script&gt;/);
 const logs=workspacePanel({...state,kind:"service",name:"omnigent.conf",mode:"logs",log:"<script>bad</script>"});
 assert.doesNotMatch(logs,/<script>/);
});
test("service template uses native fields and bounded logs",()=>{
 const template=fileTemplate("service","my-api.conf");
 for(const value of ["[program:my-api]","autorestart=true","stopasgroup=true","stdout_logfile_maxbytes=1MB"])assert.ok(template.includes(value));
 assert.match(fileTemplate("startup"),/^#!\/bin\/bash/);
});
test("unsupported images show the capability message without an editor",()=>{
 const html=workspacePanel({...state,data:null,failed:true,message:"This image does not provide Startup & services"});
 assert.match(html,/role="alert"/);assert.doesNotMatch(html,/<textarea/);
});
