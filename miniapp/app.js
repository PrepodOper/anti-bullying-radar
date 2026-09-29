// Мини-приложение — логика графика и API
window.BACKEND = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
  ? 'http://localhost:8000'
  : location.origin.replace(/:8001$/, ':8000'); // если бот на 8001, бэкенд на 8000

// Fallback если открыт как file://
if (location.protocol === 'file:') window.BACKEND = 'http://localhost:8000';

const moodEmojis = {1:'😢',2:'😕',3:'😐',4:'🙂',5:'😄'};
const moodLabels = {1:'Очень плохо',2:'Плохо',3:'Нормально',4:'Хорошо',5:'Отлично'};

function drawChart(entries){
  const canvas = document.getElementById('chart');
  if(!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr,dpr);
  const W = rect.width, H = rect.height;
  ctx.clearRect(0,0,W,H);

  // grid
  ctx.strokeStyle = '#e6e8eb';
  ctx.lineWidth = 1;
  for(let i=1;i<=5;i++){
    const y = H - 30 - (i-1)*(H-60)/4;
    ctx.beginPath(); ctx.moveTo(40,y); ctx.lineTo(W-10,y); ctx.stroke();
    ctx.fillStyle='#6b7a90'; ctx.font='11px Inter, sans-serif';
    ctx.fillText(i+' '+moodEmojis[i], 4, y+4);
  }
  if(!entries || !entries.length){
    ctx.fillStyle='#6b7a90'; ctx.font='13px Inter, sans-serif';
    ctx.fillText('Нет записей — отметь настроение', W/2-90, H/2);
    return;
  }
  // sort by date
  entries = [...entries].sort((a,b)=> new Date(a.created_at)-new Date(b.created_at));
  const n = entries.length;
  const left=40, right=W-10, top=20, bottom=H-30;
  const step = n>1 ? (right-left)/(n-1) : 0;

  // area
  ctx.beginPath();
  entries.forEach((e,i)=>{
    const x = left + i*step;
    const y = bottom - (e.mood_level-1)*(bottom-top)/4;
    if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
  });
  ctx.strokeStyle='#1a6cff'; ctx.lineWidth=2.5; ctx.stroke();
  // fill
  ctx.lineTo(left + (n-1)*step, bottom);
  ctx.lineTo(left, bottom);
  ctx.closePath();
  ctx.fillStyle='rgba(26,108,255,.08)'; ctx.fill();
  // points
  entries.forEach((e,i)=>{
    const x = left + i*step;
    const y = bottom - (e.mood_level-1)*(bottom-top)/4;
    ctx.beginPath(); ctx.arc(x,y,5,0,Math.PI*2);
    ctx.fillStyle = e.mood_level<=2 ? '#ff2e55' : e.mood_level===3 ? '#ff9500' : '#0fb27a';
    ctx.fill(); ctx.strokeStyle='#fff'; ctx.lineWidth=2; ctx.stroke();
  });
  // x labels
  ctx.fillStyle='#6b7a90'; ctx.font='10px Inter, sans-serif';
  entries.forEach((e,i)=>{
    if(n>10 && i%2===1) return;
    const x = left + i*step;
    const d = new Date(e.created_at);
    const label = d.toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit'});
    ctx.fillText(label, x-14, H-8);
  });
}

async function loadHistory(){
  const uid = document.getElementById('uid').value.trim();
  if(!uid) return;
  try{
    const r = await fetch(window.BACKEND + '/api/mood/history?max_user_id=' + encodeURIComponent(uid)).then(r=>{
      if(!r.ok) throw new Error('HTTP '+r.status);
      return r.json();
    });
    const entries = r.entries || [];
    drawChart(entries);
    // badges
    document.getElementById('countBadge').textContent = entries.length + ' записей';
    if(entries.length){
      const avg = (entries.reduce((s,e)=>s+e.mood_level,0)/entries.length).toFixed(2);
      document.getElementById('avgBadge').textContent = 'среднее ' + avg;
      document.getElementById('avgBadge').className = 'badge ' + (avg<2.5?'danger':avg<3.5?'warn':'ok');
    }
    // trigger
    const box = document.getElementById('triggerBox');
    if(r.trigger_3day){
      box.style.display='block'; box.className='notice warn';
      box.innerHTML = '⚠️ <b>Заметил, что последние три дня тебе непросто…</b><br>Хочешь поговорить с психологом? Это анонимно — он увидит только твою параллель.';
    } else {
      box.style.display='none';
    }
    // table
    const tbody=document.getElementById('tbody');
    if(tbody){
      tbody.innerHTML='';
      [...entries].sort((a,b)=> new Date(b.created_at)-new Date(a.created_at)).forEach(e=>{
        const tr=document.createElement('tr');
        tr.innerHTML=`<td>${new Date(e.created_at).toLocaleString('ru-RU')}</td><td><span class="badge ${e.mood_level<=2?'danger':e.mood_level===3?'warn':'ok'}">${e.mood_level} — ${moodLabels[e.mood_level]}</span></td><td style="font-size:18px">${moodEmojis[e.mood_level]}</td>`;
        tbody.appendChild(tr);
      });
    }
  }catch(e){
    drawChart([]);
    const box=document.getElementById('triggerBox');
    if(box){ box.style.display='block'; box.className='notice info'; box.textContent='Нет истории — сделай первую отметку. Ошибка: '+e.message; }
    console.error(e);
  }
}

// init when DOM ready
document.addEventListener('DOMContentLoaded', ()=>{
  // handle ?uid= param (из электронного дневника / QR)
  const p = new URLSearchParams(location.search);
  const uid = p.get('uid') || p.get('max_user_id');
  if(uid) document.getElementById('uid').value = uid;
  loadHistory();
  window.addEventListener('resize', ()=> {
    const uid2=document.getElementById('uid')?.value;
    if(uid2) loadHistory();
  });
});
