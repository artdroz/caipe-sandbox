import { openPolicyPanel } from "./panel.js";
import { mountCreation } from "./creation.js";
import "./style.css";

export default {
  id:"openshell", openPanel:openPolicyPanel, mountCreation,
  securitySections:[
    {id:"network",title:"Internet & network connectivity",order:10},
    {id:"startup",title:"Files & processes",order:20},
  ],
  mountSecurity:openPolicyPanel,
};
