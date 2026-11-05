import test from 'node:test';
import assert from 'node:assert/strict';
import {namespaceOptions,namespaceLockBadge} from '../namespace-view.js';

const entries=[{name:'alice-tools',owner:'alice@example.com',provider:'agentSandbox',available:true}, {name:'protected',owner:'bob@example.com',provider:'openShell',available:true}, {name:'gone',owner:'alice@example.com',provider:'agentSandbox',available:false}];
test('picker offers new and only compatible available namespaces',()=>{
 const html=namespaceOptions(entries,'agentSandbox',['perSandbox','perUser'],'bob@example.com');
 assert.match(html,/Create a new namespace/);assert.match(html,/alice-tools.*alice@example.com/);assert.doesNotMatch(html,/protected|gone|My shared namespace/);
 assert.doesNotMatch(namespaceOptions(entries,'agentSandbox',['perSandbox'],'alice@example.com'),/alice-tools/);
});
test('locked namespaces show a focusable lock icon and explanatory tooltip',()=>{
 assert.equal(namespaceLockBadge(false,'vm'),'');
 const html=namespaceLockBadge(true,'" unsafe');
 assert.match(html,/tabindex="0"/);assert.match(html,/role="tooltip"/);assert.match(html,/no one can create new sandboxes here/);
 assert.match(html,/namespace-lock-&quot; unsafe/);assert.doesNotMatch(html,/id="namespace-lock-" unsafe/);
});
