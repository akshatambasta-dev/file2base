(() => {
  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      const prompt = form.getAttribute('data-confirm');
      if (prompt && !window.confirm(prompt)) event.preventDefault();
    });
  });

  const input = document.getElementById('file-input');
  const browse = document.getElementById('browse-files');
  const dropzone = document.querySelector('.dropzone');
  const selected = document.getElementById('selected-files');
  const submit = document.getElementById('upload-submit');
  const form = document.getElementById('upload-form');

  if (input && browse && dropzone && selected && submit && form) {
    const renderFiles = (files) => {
      selected.innerHTML = '';
      const list = Array.from(files || []);
      if (!list.length) {
        submit.disabled = true;
        return;
      }
      if (list.length > 8) {
        const warning = document.createElement('div');
        warning.className = 'selected-warning';
        warning.textContent = 'Choose up to 8 files per workspace.';
        selected.appendChild(warning);
        submit.disabled = true;
        return;
      }
      list.forEach((file) => {
        const item = document.createElement('div');
        item.className = 'selected-file';
        const icon = document.createElement('span');
        icon.className = 'selected-file-icon';
        icon.textContent = file.name.toLowerCase().endsWith('.xlsx') ? 'X' : '▤';
        const name = document.createElement('span');
        name.className = 'selected-file-name';
        name.textContent = file.name;
        const size = document.createElement('small');
        size.textContent = `${Math.max(1, Math.round(file.size / 1024))} KB`;
        item.append(icon, name, size);
        selected.appendChild(item);
      });
      submit.disabled = false;
    };

    browse.addEventListener('click', () => input.click());
    input.addEventListener('change', () => renderFiles(input.files));
    ['dragenter', 'dragover'].forEach((eventName) => {
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.add('is-dragging');
      });
    });
    ['dragleave', 'drop'].forEach((eventName) => {
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropzone.classList.remove('is-dragging');
      });
    });
    dropzone.addEventListener('drop', (event) => {
      if (event.dataTransfer && event.dataTransfer.files) {
        const transfer = new DataTransfer();
        Array.from(event.dataTransfer.files).forEach((file) => transfer.items.add(file));
        input.files = transfer.files;
        renderFiles(input.files);
      }
    });
    form.addEventListener('submit', (event) => {
      if (!input.files.length) {
        event.preventDefault();
        return;
      }
      submit.disabled = true;
      submit.innerHTML = '<span class="button-spinner"></span> Analyzing files…';
    });
  }

  const schemaForm = document.getElementById('schema-form');
  if (schemaForm) {
    schemaForm.addEventListener('submit', () => {
      const button = document.getElementById('create-db-button');
      if (button) {
        button.disabled = true;
        button.innerHTML = '<span class="button-spinner"></span> Checking migration safety…';
      }
    });
  }


  const selectSafeLinks = document.getElementById('select-safe-links');
  const clearLinks = document.getElementById('clear-links');
  if (selectSafeLinks) {
    selectSafeLinks.addEventListener('click', () => {
      document.querySelectorAll('.relationship-card input[type="checkbox"]').forEach((checkbox) => {
        const status = checkbox.closest('.relationship-card')?.querySelector('.status-safe');
        checkbox.checked = Boolean(status);
      });
    });
  }
  if (clearLinks) {
    clearLinks.addEventListener('click', () => {
      document.querySelectorAll('.relationship-card input[type="checkbox"]').forEach((checkbox) => { checkbox.checked = false; });
    });
  }

  // Draw a lightweight, dependency-free relationship map for schema review.
  const graphRoot = document.getElementById('relationship-map');
  const graphNodes = document.getElementById('relationship-map-nodes');
  const graphSvg = document.getElementById('relationship-map-lines');
  const graphDataEl = document.getElementById('file2base-graph-data');
  if (graphRoot && graphNodes && graphSvg && graphDataEl) {
    let graphData = { tables: [], relationships: [] };
    try { graphData = JSON.parse(graphDataEl.textContent || '{}'); } catch (_e) {}
    const drawGraph = () => {
      const rootRect = graphRoot.getBoundingClientRect();
      const width = Math.max(1, graphRoot.clientWidth);
      const height = Math.max(1, graphRoot.clientHeight);
      graphSvg.setAttribute('width', String(width));
      graphSvg.setAttribute('height', String(height));
      graphSvg.setAttribute('viewBox', `0 0 ${width} ${height}`);
      graphSvg.querySelectorAll('.dynamic-edge').forEach((node) => node.remove());
      const positions = new Map();
      graphNodes.querySelectorAll('.graph-node').forEach((node) => {
        const rect = node.getBoundingClientRect();
        positions.set(node.dataset.tableName, {
          left: rect.left - rootRect.left, right: rect.right - rootRect.left,
          top: rect.top - rootRect.top, bottom: rect.bottom - rootRect.top,
          x: rect.left - rootRect.left + rect.width / 2,
          y: rect.top - rootRect.top + rect.height / 2
        });
      });
      (graphData.relationships || []).forEach((rel) => {
        const source = positions.get(rel.source_table);
        const target = positions.get(rel.target_table);
        if (!source || !target || rel.source_table === rel.target_table) return;
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const dx = target.x - source.x; const dy = target.y - source.y;
        const len = Math.max(1, Math.hypot(dx, dy));
        const ux = dx / len; const uy = dy / len;
        const sx = source.x + ux * 60; const sy = source.y + uy * 31;
        const tx = target.x - ux * 60; const ty = target.y - uy * 31;
        const bend = Math.min(55, Math.abs(dx) * .12);
        line.setAttribute('d', `M ${sx} ${sy} C ${sx + bend} ${sy}, ${tx - bend} ${ty}, ${tx} ${ty}`);
        line.setAttribute('fill', 'none'); line.setAttribute('stroke', '#88a8df');
        line.setAttribute('stroke-width', '1.7'); line.setAttribute('stroke-dasharray', '4 4');
        line.setAttribute('marker-end', 'url(#arrowhead)'); line.setAttribute('class', 'dynamic-edge');
        graphSvg.appendChild(line);
        const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        label.textContent = rel.source_column || '';
        label.setAttribute('x', String((sx + tx) / 2)); label.setAttribute('y', String((sy + ty) / 2 - 6));
        label.setAttribute('text-anchor', 'middle'); label.setAttribute('font-size', '9');
        label.setAttribute('font-family', 'DM Sans, sans-serif'); label.setAttribute('fill', '#6e83a6');
        label.setAttribute('class', 'dynamic-edge'); graphSvg.appendChild(label);
      });
    };
    requestAnimationFrame(() => requestAnimationFrame(drawGraph));
    window.addEventListener('resize', drawGraph);
  }

})();
