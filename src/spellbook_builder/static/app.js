(() => {
  document.addEventListener('submit', (submitEvent) => {
    const message = submitEvent.target.dataset.confirm;
    if (message && !window.confirm(message)) submitEvent.preventDefault();
  });

  const className = document.querySelector('#class-name');
  const classLevel = document.querySelector('#class-level');
  if (className && classLevel) {
    const updateLevels = () => {
      const levels = className.selectedOptions[0]?.dataset.levels?.split(',').filter(Boolean) || [];
      classLevel.replaceChildren(...levels.map((level) => {
        const option = document.createElement('option');
        option.value = level;
        option.textContent = level === '0' ? 'Cantrip' : level;
        return option;
      }));
    };
    className.addEventListener('change', updateLevels);
    updateLevels();
  }

  const query = document.querySelector('#spell-query');
  const results = document.querySelector('#spell-results');
  if (!query || !results) return;
  const form = query.closest('form');
  let serial = 0;
  let active = -1;
  const choices = () => [...results.querySelectorAll('button')];
  const setActive = (index, scroll) => {
    const buttons = choices();
    active = buttons.length ? (index + buttons.length) % buttons.length : -1;
    buttons.forEach((button, position) => button.classList.toggle('active', position === active));
    if (scroll && active >= 0) buttons[active].scrollIntoView({ block: 'nearest' });
  };

  query.addEventListener('input', async () => {
    const current = ++serial;
    if (!query.value.trim()) {
      results.replaceChildren();
      active = -1;
      return;
    }
    const response = await fetch('/api/spells?prefix=' + encodeURIComponent(query.value));
    const values = await response.json();
    if (current !== serial) return;
    const items = values.map((value) => {
      const item = document.createElement('li');
      const button = document.createElement('button');
      const name = document.createElement('span');
      const detail = document.createElement('small');
      button.name = 'spell_id';
      button.value = value.id;
      name.textContent = value.name;
      detail.textContent = `${value.level === 0 ? 'Заговор' : `${value.level} уровень`} · ${value.school}`;
      button.append(name, detail);
      item.append(button);
      return item;
    });
    if (!items.length) {
      const empty = document.createElement('li');
      empty.className = 'muted';
      empty.textContent = 'No Russian or English spell name starts with that.';
      items.push(empty);
    }
    results.replaceChildren(...items);
    setActive(0, false);
  });

  query.addEventListener('keydown', (keyEvent) => {
    if (keyEvent.key === 'ArrowDown' || keyEvent.key === 'ArrowUp') {
      keyEvent.preventDefault();
      setActive(active + (keyEvent.key === 'ArrowDown' ? 1 : -1), true);
    } else if (keyEvent.key === 'Enter') {
      keyEvent.preventDefault();
      const button = choices()[active];
      if (button) form.requestSubmit(button);
    }
  });

  form.addEventListener('submit', (submitEvent) => {
    if (!submitEvent.submitter || !submitEvent.submitter.value) submitEvent.preventDefault();
  });
})();
