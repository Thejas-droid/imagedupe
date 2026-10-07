const $ = q => document.querySelector(q);
const $$ = q => [...document.querySelectorAll(q)];
const launchToken = new URLSearchParams(location.hash.slice(1)).get('desktop');
if(launchToken){sessionStorage.setItem('desktopToken',launchToken);history.replaceState(null,'',location.pathname+location.search);}
const desktopToken = sessionStorage.getItem('desktopToken');
let mode = sessionStorage.getItem('searchMode') || 'image';
let file = null;
let results = [];
let lastSearch = null;
let view = localStorage.getItem('view') || 'grid';
let collections = [];
let savedSettings = {};
const busyFolders = new Set();
const folderMessages = new Map();
const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const fmtBytes = n => { n = Number(n || 0); if(n < 1024) return `${n} B`; if(n < 1024**2) return `${(n/1024).toFixed(1)} KiB`; if(n < 1024**3) return `${(n/1024**2).toFixed(1)} MiB`; return `${(n/1024**3).toFixed(2)} GiB`; };
const fmtDate = v => v ? new Date(v).toLocaleString() : '—';
function toast(text){ $('#toast').textContent = text; $('#toast').className='show'; setTimeout(()=>$('#toast').className='',2600); }
async function api(url, options={}){ const headers=new Headers(options.headers||{});if(desktopToken)headers.set('X-ImageDupe-Desktop',desktopToken);let response;try{response=await fetch(url,{...options,headers})}catch{throw Error('Cannot reach ImageDupe. Keep the server terminal open, then refresh this page.');} if(response.status===204)return null; let body={}; try{body=await response.json()}catch{} if(!response.ok){const detail=Array.isArray(body.detail)?body.detail.map(e=>e.msg).join('; '):body.detail;throw Error(detail||body.title||`Request failed (${response.status}). Please try again.`);} return body; }

$$('nav button').forEach(button => button.onclick = () => showPage(button.dataset.page));
function showPage(page){
  $$('nav button').forEach(button=>{const active=button.dataset.page===page;button.classList.toggle('active',active);if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current')});
  $$('.page').forEach(section=>section.classList.toggle('active',section.id===page));
  if(page==='collections') loadCollections().catch(error=>notice(error.message,true));
  if(page==='settings') loadSettings().catch(error=>toast(error.message));
}

function setMode(next, focus=false){
  mode=next;sessionStorage.setItem('searchMode',next);
  const image=next==='image';
  $('#imageTab').setAttribute('aria-selected',String(image));$('#imageTab').tabIndex=image?0:-1;
  $('#hashTab').setAttribute('aria-selected',String(!image));$('#hashTab').tabIndex=image?-1:0;
  $('#imagePanel').hidden=!image;$('#hashPanel').hidden=image;
  if(focus)(image?$('#imageTab'):$('#hashTab')).focus();
  updateSearchState();
}
$('#imageTab').onclick=()=>setMode('image');$('#hashTab').onclick=()=>setMode('hash');
$$('[role=tab]').forEach(tab=>tab.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();setMode(mode==='image'?'hash':'image',true)}}));
setMode(mode);

const drop=$('#drop');
['dragenter','dragover'].forEach(name=>drop.addEventListener(name,event=>{event.preventDefault();drop.classList.add('drag')}));
['dragleave','drop'].forEach(name=>drop.addEventListener(name,event=>{event.preventDefault();drop.classList.remove('drag')}));
drop.addEventListener('drop',event=>pick(event.dataTransfer.files[0]));
drop.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();$('#file').click()}});
$('#file').onchange=event=>pick(event.target.files[0]);
function pick(candidate){
  if(!candidate)return;
  if(!['image/jpeg','image/png','image/webp'].includes(candidate.type)){toast('Use JPG, PNG, or WEBP');return}
  file=candidate;updateSearchState();const url=URL.createObjectURL(candidate);$('#previewImg').src=url;$('#previewName').textContent=candidate.name;$('#previewMeta').textContent=fmtBytes(candidate.size);$('#preview').hidden=false;drop.hidden=true;
  $('#previewImg').onload=()=>{ $('#previewMeta').textContent=`${$('#previewImg').naturalWidth}×${$('#previewImg').naturalHeight} · ${fmtBytes(candidate.size)}`;URL.revokeObjectURL(url); };
}
$('#remove').onclick=()=>{file=null;$('#file').value='';$('#preview').hidden=true;drop.hidden=false;updateSearchState()};

async function loadCollections(){
  collections=await api('/api/v1/collections');
  const current=$('#collection').value;
  $('#collection').innerHTML=collections.length?collections.map(c=>`<option value="${c.id}">${esc(c.name)} · ${c.counts.valid} images</option>`).join(''):'<option value="">Add an image folder first</option>';
  if(current&&!collections.some(c=>c.id===current)){results=[];lastSearch=null;render();}
  const desired=current||savedSettings.default_collection||'';if(desired && collections.some(c=>c.id===desired))$('#collection').value=desired;
  renderCollections();updateSearchState();await summary();
}
function rootText(c){ const privacy=$('#privacy').checked || savedSettings.privacy_paths; return c.roots.map(r=>privacy?`…/${String(r.path).split(/[\\/]/).filter(Boolean).pop()}`:r.path).join(', '); }
function notice(message, error=false){const el=$('#folderNotice');el.hidden=false;el.textContent=message;el.className=`notice ${error?'error':''}`;}
function matchingThreshold(){
  const c=collections.find(c=>c.id===$('#collection').value);
  const bits=c?.fingerprint_spec_id.includes('-64-')?64:256;
  const custom=$('#max').value.trim();
  if(custom!==''){
    const value=Number(custom);
    if(!Number.isInteger(value)||value<0||value>bits)throw Error(`Maximum difference must be a whole number between 0 and ${bits}.`);
    return value;
  }
  const minimum=$('#matchType').value;
  return minimum==='nearest'?null:Math.floor(bits*(100-Number(minimum))/100);
}
function updateMatchHelp(){
  const minimum=$('#matchType').value;
  $('#matchHelp').textContent=$('#max').value.trim()!==''?'Using your custom difference limit from Advanced search options. Minimum similarity is overridden.':minimum==='nearest'?'Exploration mode: includes less relevant images without a similarity cutoff.':`Images below ${minimum}% similarity are hidden. Results won’t be padded to reach the maximum.`;
}
function updateSearchState(){
  $('#onboarding').hidden=collections.length>0;
  const c=collections.find(c=>c.id===$('#collection').value);
  $('#go').disabled=!c||!c.counts.valid||(!c.active_index&&$('#backend').value!=='exact')||(mode==='image'?!file:!$('#hash').value.trim());
  $('#searchHelp').textContent=!c?'Start by adding an image folder above.':busyFolders.has(c.id)?'Preparing your folder for search. This may take a moment.':!c.counts.valid?'This folder has no searchable images yet. Open Image folders to scan it or review skipped files.':!c.active_index&&$('#backend').value!=='exact'?'Your images are scanned. Open Image folders and choose Prepare for search.':`Search ${c.counts.valid.toLocaleString()} images in ${c.name}. ${mode==='image'&&!file?'Choose a reference photo above.':''}`;
  $('#json').disabled=$('#csv').disabled=!lastSearch||!results.length;
}
function openSetup(){showPage('collections');$('#newForm').hidden=false;$('#formError').hidden=true;$('#croot').removeAttribute('aria-invalid');$('#croot').focus();}
$('#startSetup').onclick=openSetup;
function renderCollections(){
  $('#collectionCards').innerHTML=collections.length?collections.map(c=>{
    const busy=busyFolders.has(c.id)||c.health==='building',ready=c.counts.valid>0&&!!c.active_index;
    const message=folderMessages.get(c.id)||(ready?'Ready to search':c.counts.valid?'Images scanned. Prepare this folder for search.':c.last_scan_at?'No images found. Check the path or try another folder.':'Scan this folder to make its images searchable.');
    return `<article class="ccard"><div class="ccard-head"><div><h2>${esc(c.name)}</h2><div class="roots">${esc(rootText(c))}</div></div><span class="status-pill ${busy?'building':ready?'healthy':'degraded'}">${busy?'Preparing…':ready?'Ready to search':'Needs setup'}</span></div>
      <div class="folder-count"><b>${c.counts.valid.toLocaleString()}</b> searchable images <span>· ${c.counts.failed} couldn’t be read · ${c.counts.skipped} skipped</span></div>
      <p class="folder-progress" role="status">${esc(message)}</p>
      <div class="actions"><button class="primary" data-action="search" data-id="${c.id}" ${!ready?'disabled':''}>Search this folder →</button><button data-action="${c.counts.valid&&!c.active_index?'build':'scan'}" data-id="${c.id}" ${busy?'disabled':''}>${c.counts.valid&&!c.active_index?'Prepare for search':c.last_scan_at?'Scan for changes':'Scan images'}</button><button data-action="failures" data-id="${c.id}">Review unreadable files</button></div>
      <details class="advanced"><summary>Folder details &amp; management</summary><div class="facts"><div class="fact"><small>Last scanned</small><b>${fmtDate(c.last_scan_at)}</b></div><div class="fact"><small>Unique fingerprints</small><b>${c.counts.unique_buckets}</b></div><div class="fact"><small>Search engine</small><b>${esc(c.active_index?.backend||'Automatic')}</b></div></div><div class="actions"><button data-action="build" data-id="${c.id}" ${busy||!c.counts.valid?'disabled':''}>Optimize search index</button><button data-action="benchmark" data-id="${c.id}" ${busy||!ready?'disabled':''}>Test search performance</button><button data-action="indexes" data-id="${c.id}">Index history</button><button class="danger" data-action="remove" data-id="${c.id}" ${busy?'disabled':''}>Remove folder</button></div></details></article>`;
  }).join(''):'<div class="empty-state panel"><span class="empty-icon" aria-hidden="true">▧</span><h2>A home for your photo folders</h2><p>Add your Downloads or Pictures folder to get started.<br>We’ll find the supported images, including those in subfolders.</p><button class="primary" data-action="add">+ Add your first folder</button></div>';
}
$('#collectionCards').onclick=event=>{
  const button=event.target.closest('[data-action]');if(!button||button.disabled)return;
  const id=button.dataset.id,c=collections.find(c=>c.id===id);
  const actions={add:openSetup,search:()=>openSearch(id),scan:()=>scan(id),build:()=>build(id),failures:()=>failures(id,c.name),benchmark:()=>benchmark(id),indexes:()=>indexes(id,c.name),remove:()=>removeC(id)};
  actions[button.dataset.action]?.();
};
window.openSearch=id=>{showPage('search');$('#collection').value=id;results=[];lastSearch=null;$('#status').textContent='';render();updateSearchState();summary();(mode==='image'?$('#drop'):$('#hash')).focus()};
async function startJob(id,type){
  if(busyFolders.has(id))return;
  busyFolders.add(id);folderMessages.set(id,type==='scan'?'Starting image scan…':'Preparing search index…');renderCollections();updateSearchState();
  try{const job=await api(`/api/v1/collections/${id}/${type==='scan'?'scan':'rebuild'}`,type==='scan'?{method:'POST'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({backend:'auto',config:{}})});const finished=await poll(job.job_id,id);
    if(type==='scan'&&finished.state==='SUCCEEDED'&&collections.find(c=>c.id===id)?.counts.valid){
      folderMessages.set(id,'Images scanned. Preparing them for search…');notice('Images scanned. Preparing them for search…');renderCollections();
      const indexJob=await api(`/api/v1/collections/${id}/rebuild`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({backend:'auto',config:{}})});await poll(indexJob.job_id,id);
    }
  }
  catch(error){folderMessages.set(id,error.message);notice(error.message,true);}
  finally{busyFolders.delete(id);renderCollections();updateSearchState();}
}
window.scan=id=>startJob(id,'scan');
window.build=id=>startJob(id,'rebuild');
window.benchmark=async id=>{try{toast('Benchmark running');const report=await api(`/api/v1/collections/${id}/indexes/benchmark?k=20&queries=50`,{method:'POST'});showDialog('Benchmark',`<div class="facts"><div class="fact"><small>Backend</small><b>${esc(report.backend||'—')}</b></div><div class="fact"><small>Recall@${report.k}</small><b>${Number(report.recall_at_k).toFixed(4)}</b></div><div class="fact"><small>p50</small><b>${Number(report.p50_ms).toFixed(2)} ms</b></div><div class="fact"><small>p95</small><b>${Number(report.p95_ms).toFixed(2)} ms</b></div></div><pre>${esc(JSON.stringify(report,null,2))}</pre>`)}catch(error){toast(error.message)}};
window.failures=async(id,name)=>{try{const rows=await api(`/api/v1/collections/${id}/failures`);showDialog(`${name} · failed files`, rows.length?`<div class="table-wrap"><table><thead><tr><th>Path</th><th>Error</th><th>Size</th><th>Updated</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.relative_path)}</td><td>${esc(r.error_code||'—')}</td><td>${fmtBytes(r.byte_size)}</td><td>${fmtDate(r.updated_at)}</td></tr>`).join('')}</tbody></table></div>`:'<p>No failed files.</p>')}catch(error){toast(error.message)}};
window.indexes=async(id,name)=>{try{const rows=await api(`/api/v1/collections/${id}/indexes`);showDialog(`${name} · generations`, rows.length?`<div class="table-wrap"><table><thead><tr><th>Gen</th><th>Backend</th><th>Status</th><th>Vectors</th><th>Revision</th><th>Built</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.generation}</td><td>${esc(r.backend)}</td><td>${esc(r.status)}</td><td>${r.vector_count}</td><td>${r.catalog_revision}</td><td>${fmtDate(r.build_ended_at)}</td></tr>`).join('')}</tbody></table></div>`:'<p>No generations.</p>')}catch(error){toast(error.message)}};
window.removeC=async id=>{if(confirm('Remove this folder from ImageDupe? Your original photos will stay on your computer.')){try{await api(`/api/v1/collections/${id}`,{method:'DELETE'});toast('Folder removed');await loadCollections()}catch(error){toast(error.message)}}};
async function poll(id,cid){
  for(;;){
    const job=await api(`/api/v1/jobs/${id}`),p=job.progress||{};
    const message=job.type==='scan'?`Scanning images… ${p.discovered||0} found · ${(p.hashed||0)+(p.cached||0)+(p.content_reused||0)} processed`:'Preparing the search index…';
    folderMessages.set(cid,message);renderCollections();notice(message);
    if(['SUCCEEDED','FAILED','CANCELLED','ABORTED'].includes(job.state)){
      await loadCollections();const c=collections.find(c=>c.id===cid);
      const done=job.state==='SUCCEEDED'?(job.type==='scan'?(c?.counts.valid?`Scan complete. ${c.counts.valid.toLocaleString()} images found. Preparing them for search…`:'Scan complete. No supported images found. Choose a folder with JPG, PNG, or WEBP files.'):'Your folder is ready. Choose Search this folder to find similar images.'):`${job.type==='scan'?'Scan':'Index preparation'} ${job.state.toLowerCase()}. ${job.error||'Try again or check the server terminal for details.'}`;
      folderMessages.set(cid,done);notice(done,job.state!=='SUCCEEDED');toast(done);return job;
    }
    await new Promise(resolve=>setTimeout(resolve,900));
  }
}
$('#browseFolder').onclick=async()=>{
  const button=$('#browseFolder');button.disabled=true;button.textContent='Choosing…';
  try{
    const result=await api('/api/v1/desktop/folder',{method:'POST'});
    if(result.path){$('#croot').value=result.path;$('#croot').removeAttribute('aria-invalid');$('#formError').hidden=true;$('#cname').focus();}
  }catch(error){$('#formError').textContent=error.message;$('#formError').hidden=false;}
  finally{button.disabled=false;button.textContent='Choose folder…';}
};
$('#new').onclick=openSetup;
$('#cancelNew').onclick=()=>{$('#newForm').hidden=true;$('#new').focus()};
$('#newForm').onsubmit=async event=>{
  event.preventDefault();const button=$('#createFolder');button.disabled=true;button.textContent='Adding folder…';$('#formError').hidden=true;$('#croot').removeAttribute('aria-invalid');
  const path=$('#croot').value.trim().replace(/^["']|["']$/g,'');
  const name=$('#cname').value.trim()||path.split(/[\\/]/).filter(Boolean).pop()||'My images';
  let created=null;
  try{
    created=await api('/api/v1/collections',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,roots:[{path,recursive:$('#crecursive').checked,follow_symlinks:$('#csymlink').checked,exclude_globs:$('#cexclude').value.split(',').map(x=>x.trim()).filter(Boolean),include_globs:[]}],fingerprint_spec_id:$('#cspec').value,backend_policy:$('#cbackend').value})});
    event.target.reset();event.target.hidden=true;notice('Folder added. Starting the scan…');await loadCollections();await scan(created.id);
  }catch(error){
    if(created){notice(`Folder added, but the scan could not start: ${error.message}. Use Scan images to try again.`,true);}
    else{const message=error.message.includes('not a directory')?'We couldn’t find that folder. Copy its full path from File Explorer (for example C:\\Pictures) and make sure it exists on the computer running ImageDupe.':error.message;$('#formError').textContent=message;$('#formError').hidden=false;$('#croot').setAttribute('aria-invalid','true');$('#croot').focus();}
  }finally{button.disabled=false;button.textContent='Add folder & scan images';}
};

$('#go').onclick=async()=>{
  const cid=$('#collection').value;if(!cid){openSetup();return}
  $('#status').textContent='Searching…';$('#go').disabled=true;
  try{
    const threshold=matchingThreshold();let data;
    if(mode==='image'){
      if(!file)throw Error('Select an image');
      const form=new FormData();form.append('image',file);form.append('collection_id',cid);form.append('k',$('#k').value);form.append('backend',$('#backend').value);
      if(threshold!==null)form.append('max_hamming',String(threshold));
      data=await api('/api/v1/search/image',{method:'POST',body:form});
    }else{
      data=await api('/api/v1/search/hash',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({collection_id:cid,hash:$('#hash').value,k:+$('#k').value,backend:$('#backend').value,max_hamming:threshold})});
    }
    results=data.results;lastSearch=data;render();
    $('#status').textContent=threshold===null?`Showing ${results.length} nearest image${results.length===1?'':'s'}. These may include unrelated images.`:results.length?`Found ${results.length} match${results.length===1?'':'es'} within your similarity limit (up to ${data.search.k} requested). We don’t add weak matches to fill the list.`:'No images meet your similarity limit. Lower Minimum similarity or try another reference photo.';
    $('#resultsTitle').focus();await summary();
  }catch(error){toast(error.message);$('#status').textContent=error.message}
  finally{updateSearchState()}
};
function render(){const box=$('#results');box.className=view;$('#grid').setAttribute('aria-pressed',String(view==='grid'));$('#list').setAttribute('aria-pressed',String(view==='list'));box.innerHTML=results.length?results.map(r=>`<article class="card"><span class="rank">#${r.rank}</span><img src="${r.thumbnail_url}" alt="Thumbnail for ${esc(r.filename)}" loading="lazy"><div class="body"><b>${esc(r.filename)}</b><div class="meta"><span>${r.hash_similarity_pct.toFixed(1)}% visual similarity</span></div><div class="meta"><span class="class">${esc({'BYTE_EXACT':'Identical file','PERCEPTUAL_HASH_EXACT':'Same visual fingerprint','NEAR_DUPLICATE':'Similar image','NEAREST_RESULT':'Closest match'}[r.classification]||r.classification)}</span><span>${r.width}×${r.height} · ${fmtBytes(r.bytes)}</span></div><details class="detail"><summary>Image details</summary><span>${esc(r.relative_path)}</span><span>Image ID ${r.image_id} · SHA-256 ${esc(r.sha256)}…</span><span>${esc(r.fingerprint_spec)} · ${esc(r.backend)} · generation ${r.index_generation??'live exact'}</span></details></div></article>`).join(''):lastSearch?'<div class="empty-state"><h3>No close matches found</h3><p>No images meet your similarity limit. Try another photo or lower Minimum similarity. Show all · exploration includes less relevant images.</p></div>':'<div class="empty-state"><span class="empty-icon" aria-hidden="true">▧</span><h3>Your matches will appear here</h3><p>Choose a reference photo above to find similar images.</p></div>'}
$('#grid').onclick=()=>{view='grid';localStorage.setItem('view',view);render()};$('#list').onclick=()=>{view='list';localStorage.setItem('view',view);render()};
function download(name,type,text){const url=URL.createObjectURL(new Blob([text],{type}));const anchor=document.createElement('a');anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
$('#json').onclick=()=>download('imagedupe-results.json','application/json',JSON.stringify({query:lastSearch?.query||null,search:lastSearch?.search||null,results},null,2));
function csv(value){let text=String(value??'');if(/^[=+\-@]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"'}
$('#csv').onclick=()=>{const fields=['rank','image_id','filename','relative_path','width','height','bytes','hamming_distance','fingerprint_bits','hash_similarity_pct','classification','backend','index_generation','fingerprint_spec'];download('imagedupe-results.csv','text/csv',fields.join(',')+'\n'+results.map(r=>fields.map(field=>csv(r[field])).join(',')).join('\n'))};

async function summary(){const cid=$('#collection').value;if(!cid){$('#summary').innerHTML='';return}try{const s=await api(`/api/v1/system/status?collection_id=${cid}`);const metrics=[['Total Images',s.total_images],['Unique Hashes',s.unique_fingerprints],['Indexes',s.total_indexes],['Index Size',fmtBytes(s.index_size_bytes)],['Avg Query',`${(+s.avg_query_ms).toFixed(1)} ms`],['p95 Query',`${(+s.p95_query_ms).toFixed(1)} ms`],['Status',s.system_status]];$('#summary').innerHTML=metrics.map(([name,value])=>`<div class="metric"><small>${name}</small><b>${esc(value)}</b></div>`).join('');$('#backend option[value=hnsw]').disabled=!s.backends['faiss-binary-hnsw'].available;$('#backend option[value=hnsw]').title=s.backends['faiss-binary-hnsw'].available?'':'FAISS BinaryHNSW is not installed';$('#backend option[value=ngt]').disabled=!s.backends['ngt-hamming'].available;$('#backend option[value=ngt]').title=s.backends['ngt-hamming'].available?'':'NGT is not installed';$('#backendHint').textContent=s.needs_compaction?'This folder has changed since its search index was created. Use Optimize search index in folder details to refresh it.':'';setHealth(s.system_status)}catch(error){toast(error.message)}}
$('#collection').onchange=()=>{results=[];lastSearch=null;$('#status').textContent='';render();updateSearchState();summary()};
$('#hash').oninput=updateSearchState;
$('#backend').onchange=updateSearchState;
$('#matchType').onchange=()=>{$('#max').value='';updateMatchHelp()};
$('#max').oninput=updateMatchHelp;
function setHealth(status){$('#health').textContent=status[0].toUpperCase()+status.slice(1);$('#health').className=`health ${status}`}

async function loadSettings(){const [payload,diagnostics]=await Promise.all([api('/api/v1/settings'),api('/api/v1/system/doctor')]);savedSettings={...payload.runtime,...payload.saved};$('#defaultCollection').innerHTML='<option value="">None</option>'+collections.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('');$('#defaultCollection').value=savedSettings.default_collection||'';$('#defaultK').value=savedSettings.default_top_k||20;$('#defaultSpec').value=savedSettings.default_fingerprint_spec_id||'phash-v1-256-exif-luma';$('#defaultBackend').value=savedSettings.backend_selection||'auto';$('#annProfile').value=savedSettings.ann_tuning_profile||'balanced';$('#workers').value=savedSettings.worker_count_configured??savedSettings.worker_count??0;$('#hashTimeout').value=savedSettings.hash_timeout_seconds||120;$('#uploadMiB').value=Math.round((savedSettings.max_upload_bytes||20971520)/1048576);$('#queryPixels').value=savedSettings.max_decoded_pixels||50000000;$('#ingestPixels').value=savedSettings.ingest_max_decoded_pixels||150000000;$('#thumbCache').checked=savedSettings.thumbnail_cache_enabled!==false;$('#privacy').checked=savedSettings.privacy_paths!==false;$('#cudaMode').value=savedSettings.cuda_mode||'Auto';$('#logLevel').value=savedSettings.logging_verbosity||'INFO';$('#cacheLocation').value=savedSettings.cache_location||'';const cudaOn=$('#cudaMode option[value="On"]');if(cudaOn){cudaOn.disabled=!diagnostics.faiss_binary_gpu_compatible;cudaOn.title=cudaOn.disabled?'Compatible FAISS binary GPU support was not detected':''}$('#cspec').value=savedSettings.default_fingerprint_spec_id||'phash-v1-256-exif-luma';$('#cbackend').value=savedSettings.backend_selection||'auto';$('#doctor').textContent=JSON.stringify(diagnostics,null,2);renderCollections()}
$('#settingsForm').onsubmit=async event=>{event.preventDefault();const body={default_collection:$('#defaultCollection').value||null,default_top_k:+$('#defaultK').value,default_fingerprint_spec_id:$('#defaultSpec').value,backend_selection:$('#defaultBackend').value,ann_tuning_profile:$('#annProfile').value,worker_count:+$('#workers').value,hash_timeout_seconds:+$('#hashTimeout').value,max_upload_bytes:+$('#uploadMiB').value*1048576,max_decoded_pixels:+$('#queryPixels').value,ingest_max_decoded_pixels:+$('#ingestPixels').value,thumbnail_cache_enabled:$('#thumbCache').checked,privacy_paths:$('#privacy').checked,cuda_mode:$('#cudaMode').value,logging_verbosity:$('#logLevel').value};try{const result=await api('/api/v1/settings',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});savedSettings={...result.runtime,...result.saved};toast('Settings saved');renderCollections();await summary()}catch(error){toast(error.message)}};

function showDialog(title,body){$('#dialogTitle').textContent=title;$('#dialogBody').innerHTML=body;$('#detailDialog').showModal()}$('#closeDialog').onclick=()=>$('#detailDialog').close();$('#detailDialog').addEventListener('click',event=>{if(event.target===$('#detailDialog'))$('#detailDialog').close()});

(async()=>{try{
  if(desktopToken)await api('/api/v1/desktop/session',{method:'POST'});
  const desktop=await api('/api/v1/desktop');
  $('#browseFolder').hidden=!desktop.folder_picker;$('#desktopNote').hidden=!desktop.enabled;
  if(desktop.folder_picker)$('#pathHelp').textContent='Choose a folder on this computer, or paste its full path. Your original photos stay in place.';
  await loadCollections();const s=await api('/api/v1/system/status');setHealth(s.system_status||'healthy');const settings=await api('/api/v1/settings');savedSettings={...settings.runtime,...settings.saved};$('#k').value=String(savedSettings.default_top_k||20);$('#backend').value=savedSettings.backend_selection||'auto';if(savedSettings.default_collection&&collections.some(c=>c.id===savedSettings.default_collection)){$('#collection').value=savedSettings.default_collection;await summary()}updateSearchState()}catch(error){setHealth('degraded');$('#searchHelp').textContent=error.message;toast(error.message)}})();
