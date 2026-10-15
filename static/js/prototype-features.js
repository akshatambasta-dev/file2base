(() => {
  const contextNode = document.getElementById('file2base-assistant-context');
  const form = document.getElementById('assistant-form');
  const input = document.getElementById('assistant-question');
  const messages = document.getElementById('assistant-messages');
  let context = { summary: {}, tables: [], relationships: [], quality: {} };
  if (contextNode) { try { context = JSON.parse(contextNode.textContent || '{}'); } catch (_error) {} }

  const tables = Array.isArray(context.tables) ? context.tables : [];
  const relationships = Array.isArray(context.relationships) ? context.relationships : [];
  const quality = context.quality || {};
  const summary = context.summary || {};
  const n = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
  const pct = (value) => `${Math.round(n(value))}%`;

  function answer(question) {
    const q = question.toLowerCase();
    const recs = Array.isArray(quality.recommendations) ? quality.recommendations : [];
    if (/fix first|improv|recommend|problem|issue|priority|start with/.test(q)) {
      return `Your workspace scores ${n(quality.score)}/100 for its heuristic data-quality profile (${quality.label || 'review recommended'}).\n\n${recs.map((item, i) => `${i + 1}. ${item}`).join('\n')}\n\nReview table identifiers and relationship choices, then run the migration safety check.`;
    }
    if (/duplicate|repeat/.test(q)) return n(quality.duplicate_rows) ? `The profile detected ${n(quality.duplicate_rows).toLocaleString()} exact duplicate row(s). File2Base does not delete them automatically because repeated rows may be meaningful. Inspect them and decide whether to keep them.` : 'The current profile reports no exact duplicate rows. That does not rule out near-duplicates such as differently formatted company names; fuzzy matching is not part of this prototype yet.';
    if (/strongest|relationship|connect|foreign key|link/.test(q)) {
      const link = [...relationships].sort((a,b) => n(b.coverage_pct)-n(a.coverage_pct) || n(b.confidence_pct)-n(a.confidence_pct))[0];
      return link ? `The strongest coverage candidate is ${link.source_table}.${link.source_column} → ${link.target_table}.${link.target_column}. Its value coverage is ${pct(link.coverage_pct)} and its heuristic ranking is ${pct(link.confidence_pct)}.\n\nEvidence: ${link.reason || 'field name, value overlap and type compatibility were evaluated.'} Review the checkbox yourself; this score is not a calibrated probability.` : 'No candidate relationships were detected. You can still create independent tables. Files with shared identifiers—such as customer IDs or product IDs—make relationship detection easier.';
    }
    if (/table.*attention|attention.*table|missing|null|blank|completeness/.test(q)) {
      const ranked = tables.map(table => { const cols=table.columns||[]; return {table, completeness:cols.length?cols.reduce((sum,c)=>sum+(100-n(c.null_pct)),0)/cols.length:100, missing:cols.filter(c=>n(c.null_pct)>0).sort((a,b)=>n(b.null_pct)-n(a.null_pct))}; }).sort((a,b)=>a.completeness-b.completeness);
      if (!ranked.length) return 'I do not have table profiles to compare yet.';
      const weakest=ranked[0]; const detail=weakest.missing.length? `Columns with the most missing values include ${weakest.missing.slice(0,3).map(c=>`${c.name} (${pct(c.null_pct)} null)`).join(', ')}.`:'No missing-value-heavy column stood out.';
      return `${weakest.table.name} has the lowest average column completeness at about ${Math.round(weakest.completeness)}%. ${detail}\n\nThis is based on null percentages; it cannot judge whether a missing value is acceptable for your business rules.`;
    }
    if (/primary key|identifier|row id|key/.test(q)) return `${tables.map(table=>`${table.name}: ${table.primary_key ? `candidate key ${table.primary_key}` : 'no reliable source key detected; generated row ID is available'}`).join('\n')}\n\nA generated ID gives every row a database key; it does not establish business identity across separate files.`;
    if (/safe|ready|migrat|what happens|next step/.test(q)) return 'Next, select the relationships you want to keep and click “Review migration plan”. File2Base checks identifier completeness and uniqueness, type warnings, duplicate rows, unmatched relationship values and source-file fingerprints. If blocking issues remain, migration is paused. If checks pass, the app builds a temporary SQLite database and validates it before offering a download.';
    if (/score|quality/.test(q)) return `The heuristic score is ${n(quality.score)}/100: completeness ${pct(quality.completeness)}, duplicate cleanliness ${pct(quality.duplicate_cleanliness)}, identifier readiness ${pct(quality.identifier_readiness)}, and relationship coverage ${pct(quality.relationship_coverage)}. It is an explainable prototype indicator—not a certification or ML prediction.`;
    return `This workspace contains ${n(summary.file_count)} file(s), ${tables.length} table(s), ${n(summary.row_count).toLocaleString()} row(s), ${n(summary.column_count)} profiled columns, and ${relationships.length} relationship candidate(s).\n\nAsk about quality, missing values, duplicates, identifiers, relationship evidence, or migration safety.`;
  }
  function addMessage(role, text) {
    const node=document.createElement('div');
    node.className=`assistant-message ${role}`;
    node.textContent=text;
    messages.appendChild(node);
    messages.scrollTop=messages.scrollHeight;
  }
  function ask(question) {
    const clean=String(question||'').trim();
    if(!clean || !messages) return;
    addMessage('user',clean);
    addMessage('assistant',answer(clean));
    if (input) { input.value=''; input.focus(); }
  }
  if (form && input && messages) {
    form.addEventListener('submit', event => { event.preventDefault(); ask(input.value); });
    document.querySelectorAll('[data-assistant-prompt]').forEach(button => button.addEventListener('click',()=>ask(button.getAttribute('data-assistant-prompt'))));
  }

  // Interactive schema editor: drag cards on desktop and click a connector to toggle its relationship.
  const map = document.getElementById('relationship-map');
  const nodesRoot = document.getElementById('relationship-map-nodes');
  const svg = document.getElementById('relationship-map-lines');
  const graphNode = document.getElementById('file2base-graph-data');
  const relationshipForm = document.getElementById('schema-form');
  if (!map || !nodesRoot || !svg || !graphNode || !relationshipForm) return;
  let graph = { tables: [], relationships: [] };
  try { graph = JSON.parse(graphNode.textContent || '{}'); } catch (_error) {}
  const rels = Array.isArray(graph.relationships) ? graph.relationships : [];
  const byName = new Map(Array.from(nodesRoot.querySelectorAll('.graph-node')).map(node => [node.dataset.tableName, node]));
  const relationCheckbox = (rel) => relationshipForm.querySelector(`input[name="relationship_ids"][value="${String(rel.suggestion_id)}"]`);
  function point(node, rect) {
    const b = node.getBoundingClientRect();
    return { x: b.left - rect.left + b.width/2, y: b.top - rect.top + b.height/2 };
  }
  function drawSchemaLinks() {
    const rect = map.getBoundingClientRect();
    const width = Math.max(map.clientWidth, 1), height = Math.max(map.clientHeight, 1);
    svg.setAttribute('width', String(width)); svg.setAttribute('height', String(height));
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.querySelectorAll('.feature-edge,.feature-edge-label').forEach(el => el.remove());
    // Fade the legacy decorative map edges; the active edges below are accurate to checkboxes.
    svg.querySelectorAll('.dynamic-edge').forEach(el => { el.setAttribute('opacity','0.08'); el.setAttribute('pointer-events','none'); });
    rels.forEach((rel) => {
      const checkbox = relationCheckbox(rel);
      const sourceNode = byName.get(rel.source_table), targetNode = byName.get(rel.target_table);
      if (!checkbox || !checkbox.checked || !sourceNode || !targetNode || rel.source_table === rel.target_table) return;
      const s = point(sourceNode, rect), t = point(targetNode, rect);
      const dx = t.x - s.x, dy = t.y - s.y, len = Math.max(1, Math.hypot(dx,dy));
      const ux = dx/len, uy = dy/len;
      const sx=s.x+ux*55, sy=s.y+uy*30, tx=t.x-ux*55, ty=t.y-uy*30;
      const bend=Math.min(60,Math.abs(dx)*.14);
      const path=document.createElementNS('http://www.w3.org/2000/svg','path');
      path.setAttribute('d',`M ${sx} ${sy} C ${sx+bend} ${sy}, ${tx-bend} ${ty}, ${tx} ${ty}`);
      path.setAttribute('class','feature-edge'); path.setAttribute('role','button'); path.setAttribute('tabindex','0');
      path.setAttribute('aria-label',`Disable relationship ${rel.source_table}.${rel.source_column} to ${rel.target_table}.${rel.target_column}`);
      path.setAttribute('marker-end','url(#arrowhead)');
      const toggle = () => { checkbox.checked = !checkbox.checked; checkbox.dispatchEvent(new Event('change',{bubbles:true})); drawSchemaLinks(); };
      path.addEventListener('click',toggle);
      path.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();toggle();}});
      svg.appendChild(path);
      const label=document.createElementNS('http://www.w3.org/2000/svg','text');
      label.textContent=rel.source_column || '';
      label.setAttribute('x',String((sx+tx)/2)); label.setAttribute('y',String((sy+ty)/2-7));
      label.setAttribute('text-anchor','middle'); label.setAttribute('class','feature-edge-label');
      svg.appendChild(label);
    });
  }
  let redrawFrame=0;
  const scheduleRedraw=()=>{if(redrawFrame)cancelAnimationFrame(redrawFrame);redrawFrame=requestAnimationFrame(drawSchemaLinks);};
  relationshipForm.querySelectorAll('input[name="relationship_ids"]').forEach(box=>box.addEventListener('change',scheduleRedraw));
  if (window.matchMedia('(pointer:fine)').matches) {
    nodesRoot.querySelectorAll('.graph-node').forEach(node=>{
      node.classList.add('schema-draggable');
      let dragging=false, startX=0, startY=0, baseX=0, baseY=0;
      const getOffset=()=>{const match=(node.style.getPropertyValue('--schema-x')||'0px').match(/-?[\d.]+/);const matchY=(node.style.getPropertyValue('--schema-y')||'0px').match(/-?[\d.]+/);return [match?Number(match[0]):0,matchY?Number(matchY[0]):0];};
      node.addEventListener('pointerdown',event=>{
        if(event.button!==0 || event.target.closest('a,button,input,select,textarea'))return;
        dragging=true;startX=event.clientX;startY=event.clientY;[baseX,baseY]=getOffset();
        node.classList.add('schema-dragging');node.setPointerCapture(event.pointerId);event.preventDefault();
      });
      node.addEventListener('pointermove',event=>{
        if(!dragging)return;
        const x=baseX+event.clientX-startX,y=baseY+event.clientY-startY;
        node.style.setProperty('--schema-x',`${x}px`);node.style.setProperty('--schema-y',`${y}px`);
        node.style.transform=`translate(${x}px,${y}px)`;
        scheduleRedraw();
      });
      const endDrag=()=>{dragging=false;node.classList.remove('schema-dragging');};
      node.addEventListener('pointerup',endDrag);node.addEventListener('pointercancel',endDrag);
    });
  }
  window.addEventListener('resize',scheduleRedraw);
  window.addEventListener('load',scheduleRedraw,{once:true});
  setTimeout(scheduleRedraw,90);
})();
