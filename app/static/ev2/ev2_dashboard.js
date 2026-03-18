(function(){
  const $ = (id) => document.getElementById(id);
  const out = $('output');
  function params(){
    const p = new URLSearchParams();
    ['turma_id','disciplina_id','aluno_id','reference_date','month','year','periodo_id','ano_letivo_id','semestre','data_inicio','data_fim'].forEach(k=>{
      const el=$(k); if(el && el.value) p.set(k, el.value);
    });
    if ($('include_raw')?.checked) p.set('include_raw','1');
    return p;
  }
  async function show(url, opts){
    const r = await fetch(url, opts);
    const txt = await r.text();
    try { out.textContent = JSON.stringify(JSON.parse(txt), null, 2); }
    catch { out.textContent = txt; }
  }
  document.querySelectorAll('.js-preview').forEach(btn=>btn.addEventListener('click', async ()=>{
    const map=btn.dataset.map;
    const p=params().toString();
    await show(`/ev2/maps/${map}?${p}`);
  }));
  document.querySelectorAll('.js-export').forEach(btn=>btn.addEventListener('click', ()=>{
    const fmt=btn.dataset.fmt;
    const map=$('export_map_type').value;
    const p=params();
    if ($('include_debug')?.checked) p.set('include_debug','1');
    window.location.href = `/ev2/maps/${map}/export/${fmt}?`+p.toString();
  }));
  document.querySelectorAll('.js-event').forEach(btn=>btn.addEventListener('click', async ()=>{
    await show(btn.dataset.endpoint, {method: btn.dataset.method});
  }));
  document.querySelectorAll('.js-event-id').forEach(btn=>btn.addEventListener('click', async ()=>{
    const id=$('event_id').value || '1';
    const kind=btn.dataset.kind;
    if (kind==='detail') return show(`/ev2/events/${id}`);
    if (kind==='students') return show(`/ev2/events/${id}/students`, {method:'POST'});
    return show(`/ev2/events/${id}/assessments`, {method:'POST'});
  }));
})();
