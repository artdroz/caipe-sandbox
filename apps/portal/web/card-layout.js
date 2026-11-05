export function cardLayout(container) {
  function size(cards) {
    if (!cards.length) return;
    const style = getComputedStyle(container);
    const row = parseFloat(style.gridAutoRows);
    const gap = parseFloat(style.getPropertyValue("--card-vertical-gap"));
    for (const card of cards) {
      const span = `span ${Math.ceil((card.getBoundingClientRect().height + gap) / row)}`;
      if (card.style.gridRowEnd !== span) card.style.gridRowEnd = span;
    }
  }
  const observer = new ResizeObserver(entries => size(entries.map(entry => entry.target).filter(card => card.parentElement === container)));
  function clear() {
    observer.disconnect();
    container.classList.remove("masonry");
  }
  return {
    clear,
    update() {
      clear();
      const cards = [...container.querySelectorAll(":scope > .sandbox-card")];
      if (!cards.length) return;
      container.classList.add("masonry");
      size(cards);
      for (const card of cards) observer.observe(card);
    },
  };
}
