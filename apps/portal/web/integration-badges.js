import { icon } from "./icons.js";

const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const labels = { active:"Active", pending:"Pending", inactive:"Inactive", configured:"Configured", unknown:"Status unavailable", error:"Needs attention" };
const imageName = /^[a-z0-9][a-z0-9-]*\.(svg|png|webp|jpe?g)$/;
const stateOf = integration => Object.hasOwn(labels, integration.state) ? integration.state : "unknown";
const priority = new Map(["openshell", "omnigent", "kata"].map((id, index) => [id, index]));
const ordered = integrations => [...integrations].sort((a,b) => (priority.get(a.id) ?? 3) - (priority.get(b.id) ?? 3));

function badge(integration, assetBase) {
  const state = stateOf(integration);
  const description = [integration.title, integration.layer, labels[state], integration.detail].filter(Boolean).join(" · ");
  const image = imageName.test(integration.image || "") ? `<img data-integration-image src="${escape(assetBase + "/" + integration.image)}" alt="">` : "";
  return `<span class="integration-badge" data-state="${state}" title="${escape(description)}" aria-label="${escape(description)}"><span class="integration-symbol">${image}${icon(integration.icon)}</span><span class="integration-name">${escape(integration.title)}</span><i class="integration-state" aria-hidden="true"></i></span>`;
}

export function integrationBadges(integrations, {key, assetBase="assets/integrations", limit=2} = {}) {
  if (!integrations?.length) return "";
  const items = ordered(integrations);
  const shown = items.slice(0, limit), hidden = items.slice(limit);
  const overflow = hidden.length ? `<button type="button" class="integration-overflow-count" id="integration-overflow-${escape(encodeURIComponent(key))}" data-integration-items="${escape(JSON.stringify(hidden))}" data-integration-assets="${escape(assetBase)}" aria-label="${hidden.length} more integrations">+${hidden.length}</button>` : "";
  return `<span class="integration-badges" role="group" aria-label="Integrations">${shown.map(item => badge(item, assetBase)).join("")}${overflow}</span>`;
}

export function integrationTooltip(integrations, assetBase) {
  return `<div class="integration-tooltip-list" role="group" aria-label="Other integrations">${ordered(integrations).map(item => badge(item, assetBase)).join("")}</div>`;
}

export function fitIntegrationBadges(group) {
  group.classList.remove("integration-icons-only");
  const children = [...group.children];
  const gap = Number.parseFloat(getComputedStyle(group).columnGap) || 0;
  const width = children.reduce((sum, child) => sum + child.getBoundingClientRect().width, 0) + Math.max(0,children.length - 1) * gap;
  group.classList.toggle("integration-icons-only", width > group.clientWidth + 1);
}

export function integrationTooltips(root=document) {
  const tooltip = root.createElement("div");
  tooltip.id = "integration-tooltip";
  tooltip.className = "integration-tooltip";
  tooltip.setAttribute("popover", "manual");
  tooltip.setAttribute("role", "tooltip");
  root.body.append(tooltip);
  let anchor = null, closing = null, restoreFocus = false;
  const observed = new Set();
  const sizes = new root.defaultView.ResizeObserver(entries => entries.forEach(({target}) => fitIntegrationBadges(target)));
  function fitBadges() {
    for (const group of observed) if (!group.isConnected) { sizes.unobserve(group); observed.delete(group); }
    for (const group of root.querySelectorAll(".integration-badges")) {
      fitIntegrationBadges(group);
      if (!observed.has(group)) { sizes.observe(group); observed.add(group); }
    }
  }
  const cancelClose = () => clearTimeout(closing);
  function hide() {
    cancelClose();
    anchor?.removeAttribute("aria-describedby");
    anchor = null;
    tooltip.hidePopover();
  }
  function show(trigger) {
    cancelClose();
    anchor?.removeAttribute("aria-describedby");
    anchor = trigger;
    tooltip.innerHTML = integrationTooltip(JSON.parse(trigger.dataset.integrationItems), trigger.dataset.integrationAssets);
    trigger.setAttribute("aria-describedby", tooltip.id);
    if (!tooltip.matches(":popover-open")) tooltip.showPopover();
    const bounds = trigger.getBoundingClientRect(), width = tooltip.offsetWidth;
    const x = Math.max(8, Math.min(bounds.right - width, root.documentElement.clientWidth - width - 8));
    const y = bounds.bottom + tooltip.offsetHeight + 8 <= root.documentElement.clientHeight ? bounds.bottom + 6 : Math.max(8, bounds.top - tooltip.offsetHeight - 6);
    tooltip.style.left = `${x}px`;
    tooltip.style.top = `${y}px`;
  }
  function enter(event) {
    if (tooltip.contains(event.target)) { cancelClose(); return; }
    if (event.type === "pointerover" && event.pointerType === "touch") return;
    const trigger = event.target.closest?.("[data-integration-items]");
    if (trigger) show(trigger);
  }
  function leave(event) {
    if (!anchor || (!anchor.contains(event.target) && !tooltip.contains(event.target))) return;
    if (anchor.contains(event.relatedTarget) || tooltip.contains(event.relatedTarget)) return;
    cancelClose();
    closing = setTimeout(hide, 120);
  }
  root.addEventListener("pointerover", enter);
  root.addEventListener("focusin", enter);
  root.addEventListener("pointerout", leave);
  root.addEventListener("focusout", leave);
  root.addEventListener("click", event => {
    const trigger = event.target.closest?.("[data-integration-items]");
    if (trigger) show(trigger);
    else if (!tooltip.contains(event.target)) hide();
  });
  root.addEventListener("keydown", event => { if (event.key === "Escape") hide(); });
  root.addEventListener("scroll", event => { if (!tooltip.contains(event.target)) hide(); }, true);
  root.defaultView.addEventListener("resize", hide);
  root.addEventListener("error", event => {
    if (event.target.matches?.("img[data-integration-image]")) event.target.hidden = true;
  }, true);
  return {
    hide,
    beforeRender() { restoreFocus = anchor === root.activeElement; },
    afterRender() {
      fitBadges();
      if (!anchor) return;
      const replacement = root.getElementById(anchor.id);
      if (!replacement) { hide(); return; }
      if (restoreFocus) replacement.focus({preventScroll:true});
      show(replacement);
    },
  };
}
