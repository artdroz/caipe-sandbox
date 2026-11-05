import { mountPolicy } from "./panel.js";
import "./style.css";

export default {
  id:"kubernetes",
  securitySections:[{id:"network",title:"In-cluster networking",order:30}],
  mountSecurity:mountPolicy,
};
