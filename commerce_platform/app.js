'use strict';
// All figures below come from the published SQL/Python aggregate files.
// No raw transactions, individual customer identifiers or external analytics services.
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nf = new Intl.NumberFormat('ru-RU', {maximumFractionDigits:0});
const df = new Intl.NumberFormat('ru-RU', {minimumFractionDigits:1,maximumFractionDigits:1});
const number = value => Number.isFinite(Number(value)) && value !== null ? nf.format(Number(value)) : '—';
const pounds = pence => Number.isFinite(Number(pence)) && pence !== null ? '£' + number(Number(pence)/100) : '—';
const pct = value => Number.isFinite(Number(value)) && value !== null ? df.format(Number(value)*100) + '%' : '—';
const sum = (rows,key) => rows.reduce((a,r)=>a+Number(r[key]||0),0);
const monthName = month => { const [y,m] = month.split('-'); return `${m}.${y}`; };
const titles = {
 overview:['Обзор бизнеса','От операций к показателям, которые помогают выбрать следующий шаг.'],
 products:['Ассортимент','Концентрация продаж, ABC-классы и товары, требующие внимания.'],
 cohorts:['Удержание клиентов','Повторные покупки с корректными знаменателями и завершёнными окнами.'],
 forecast:['Прогноз для планирования','Три прозрачные стратегии и измеренные ошибки на будущих для них месяцах.'],
 quality:['Качество данных','Правила приёмки, источник расхождений и доказательства корректности расчётов.'],
 architecture:['Архитектура и код','От исходного XLSX до хранилища, проверенных витрин и управленческого интерфейса.']
};
let data, forecast, validation, productPage=0, currentProducts=[];
const pageSize=20;

function kpi(label,value,detail,emphasis=false){return `<article class="kpi${emphasis?' emphasis':''}"><span class="label">${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(detail)}</small></article>`;}
function setPage(name,changeHash=true){
 if(!titles[name]) name='overview';
 document.querySelectorAll('.page').forEach(e=>{e.hidden=e.id!==name;e.classList.toggle('active',e.id===name);});
 document.querySelectorAll('nav [data-page]').forEach(e=>{if(e.dataset.page===name)e.setAttribute('aria-current','page');else e.removeAttribute('aria-current');});
 $('page-title').textContent=titles[name][0];$('page-description').textContent=titles[name][1];
 if(changeHash)history.replaceState(null,'','#'+name);
 window.scrollTo({top:0,behavior:'instant'});
}
function svgLineChart(labels,series,{money=true,height=280}={}){
 if(!labels.length)return '<p class="empty">Нет данных для этого диапазона.</p>';
 const width=760,left=68,right=24,top=20,bottom=42,plotW=width-left-right,plotH=height-top-bottom;
 const values=series.flatMap(s=>s.values.filter(v=>Number.isFinite(v)));
 let max=Math.max(0,...values),min=Math.min(0,...values);if(max===min)max=min+1;
 const pad=(max-min)*.08;max+=pad;if(min<0)min-=pad;
 const x=i=>left+(labels.length===1?plotW/2:i*plotW/(labels.length-1));
 const y=v=>top+(max-v)/(max-min)*plotH;
 const axis=v=>money?(Math.abs(v)>=1000000?df.format(v/1000000)+' млн':Math.abs(v)>=1000?number(v/1000)+' тыс.':number(v)):number(v)+'%';
 let out=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(series.map(s=>s.label).join(', '))}">`;
 for(let i=0;i<=4;i++){const v=min+(max-min)*i/4;out+=`<line x1="${left}" y1="${y(v)}" x2="${width-right}" y2="${y(v)}" stroke="#e6edf1"/><text x="${left-10}" y="${y(v)+4}" text-anchor="end" font-size="10" fill="#718595">${esc(axis(v))}</text>`;}
 if(min<0)out+=`<line x1="${left}" y1="${y(0)}" x2="${width-right}" y2="${y(0)}" stroke="#9cabb5" stroke-dasharray="3 3"/>`;
 const step=Math.max(1,Math.ceil(labels.length/8));
 labels.forEach((label,i)=>{if(i%step===0||i===labels.length-1)out+=`<text x="${x(i)}" y="${height-13}" text-anchor="middle" font-size="10" fill="#718595">${esc(monthName(label))}</text>`;});
 series.forEach(s=>{
  const points=s.values.map((v,i)=>Number.isFinite(v)?`${x(i)},${y(v)}`:null).filter(Boolean).join(' ');
  out+=`<polyline points="${points}" fill="none" stroke="${s.color}" stroke-width="${s.width||2.3}" stroke-linejoin="round" ${s.dash?'stroke-dasharray="5 4"':''}/>`;
  s.values.forEach((v,i)=>{if(Number.isFinite(v))out+=`<circle cx="${x(i)}" cy="${y(v)}" r="${labels.length>15?2.2:3.5}" fill="${s.color}" tabindex="0"><title>${esc(monthName(labels[i])+' · '+s.label+': '+(money?'£'+number(v):df.format(v)+'%'))}</title></circle>`;});
 });
 return out+'</svg>';
}
function bars(rows,{max=null}={}){
 const bound=max??Math.max(1,...rows.map(r=>Math.abs(r.value)));
 return rows.map(r=>`<div class="bar-row"><div class="bar-head"><span>${esc(r.label)}</span><strong class="${r.value<0?'negative':''}">${esc(r.formatted??number(r.value))}</strong></div><div class="bar-track"><div class="bar-fill" style="width:${Math.min(100,Math.abs(r.value)/bound*100).toFixed(4)}%;background:${r.color||'#0f847c'}"></div></div></div>`).join('');
}
function filteredSales(){
 const from=$('from').value,to=$('to').value,country=$('country').value;
 return data.country_month.filter(r=>r.month>=from&&r.month<=to&&(country==='all'||r.country===country));
}
function renderOverview(){
 const invalid=$('from').value>$('to').value;$('filter-error').hidden=!invalid;$('export-sales').disabled=invalid;
 if(invalid){$('sales-kpis').innerHTML='';$('sales-chart').innerHTML='<p class="empty">Выберите корректный диапазон месяцев.</p>';$('country-chart').innerHTML='';return;}
 const rows=filteredSales(),gross=sum(rows,'gross_pence'),cancel=sum(rows,'cancel_pence'),net=sum(rows,'net_pence'),orders=sum(rows,'orders');
 $('filter-scope').textContent=monthName($('from').value)+' — '+monthName($('to').value);
 $('sales-kpis').innerHTML=[kpi('Оборот после отмен',pounds(net),'Продажи за вычетом суммы отмен',true),kpi('Продажи до отмен',pounds(gross),'Принятые положительные операции'),kpi('Заказы с продажами',number(orders),'Средний положительный заказ: '+pounds(orders?gross/orders:null)),kpi('Сумма отмен / продажи',pct(gross?cancel/gross:null),'Сумма отмен: '+pounds(cancel))].join('');
 const months=data.meta.months.filter(m=>m>=$('from').value&&m<=$('to').value);
 const monthly=months.map(month=>{const r=rows.filter(x=>x.month===month);return {month,gross:sum(r,'gross_pence')/100,cancel:sum(r,'cancel_pence')/100,net:sum(r,'net_pence')/100};});
 $('sales-chart').innerHTML=svgLineChart(months,[{label:'Продажи до отмен',color:'#0f847c',values:monthly.map(r=>r.gross)},{label:'Сумма отмен',color:'#d19455',values:monthly.map(r=>r.cancel)},{label:'Оборот после отмен',color:'#203b57',values:monthly.map(r=>r.net),width:2.7}]);
 const countries=new Map();rows.forEach(r=>countries.set(r.country,(countries.get(r.country)||0)+r.net_pence));
 const top=[...countries].sort((a,b)=>b[1]-a[1]).slice(0,8).map(([label,value])=>({label,value,formatted:pounds(value)}));
 $('country-chart').innerHTML=top.length?bars(top):'<p class="empty">Нет операций.</p>';
}
function renderInsights(){
 $('business-insights').innerHTML=(data.insights||[]).slice(0,3).map(r=>`<article class="insight"><div class="value">${esc(r.value)}</div><h3>${esc(r.title)}</h3><p>${esc(r.interpretation)}</p><p class="next"><b>Следующий шаг:</b> ${esc(r.action)}</p></article>`).join('');
}
function renderProducts(){
 const query=$('product-search').value.trim().toLowerCase(),abc=$('abc-filter').value,key=$('product-sort').value;
 currentProducts=data.products.filter(r=>(abc==='all'||r.abc===abc)&&(!query||(String(r.stock_code)+' '+r.description).toLowerCase().includes(query))).sort((a,b)=>Number(b[key])-Number(a[key])||String(a.stock_code).localeCompare(String(b.stock_code)));
 const pages=Math.max(1,Math.ceil(currentProducts.length/pageSize));productPage=Math.min(productPage,pages-1);
 $('product-table').innerHTML=currentProducts.slice(productPage*pageSize,(productPage+1)*pageSize).map(r=>`<tr><td><span class="product-code">${esc(r.stock_code)}</span><span class="product-name">${esc(r.description||'Без описания')}</span></td><td><span class="badge ${String(r.abc).toLowerCase()}">${esc(r.abc)}</span></td><td>${pounds(r.gross_pence)}</td><td>${pounds(r.cancel_pence)}</td><td>${pounds(r.net_pence)}</td><td>${number(r.orders)}</td></tr>`).join('')||'<tr><td colspan="6" class="empty">По вашему запросу товаров не найдено.</td></tr>';
 $('product-count').textContent=`${number(currentProducts.length)} позиций · страница ${productPage+1} из ${pages}`;
 $('products-prev').disabled=productPage===0;$('products-next').disabled=productPage>=pages-1;
}
function renderProductSummary(){
 const gross=sum(data.products,'gross_pence');const classes=['A','B','C'].map(abc=>{const rows=data.products.filter(p=>p.abc===abc);return {abc,count:rows.length,gross:sum(rows,'gross_pence')};});
 const a=classes[0];const top10=[...data.products].sort((a,b)=>b.gross_pence-a.gross_pence).slice(0,10);
 $('product-kpis').innerHTML=[kpi('Коды в каталоге',number(data.products.length),'Включая служебные и корректировочные'),kpi('Класс A',number(a.count)+' позиций',pct(gross?a.gross/gross:null)+' положительных продаж',true),kpi('Топ-10 по продажам',pct(gross?sum(top10,'gross_pence')/gross:null),'Доля положительных продаж'),kpi('Общий охват',pounds(gross),'Сверяется с витриной продаж')].join('');
 $('abc-chart').innerHTML=bars(classes.map((r,i)=>({label:`Класс ${r.abc} · ${number(r.count)} позиций`,value:r.gross,formatted:pct(gross?r.gross/gross:null)+' · '+pounds(r.gross),color:['#0f847c','#5277a3','#c59457'][i]})),{max:gross});
}
function renderCohorts(){
 const cohorts=[...new Set(data.cohorts.map(r=>r.cohort))].sort();
 const base=data.cohorts.filter(r=>r.age===0),m1=data.cohorts.filter(r=>r.age===1&&r.retention!==null),m3=data.cohorts.filter(r=>r.age===3&&r.retention!==null);
 const weighted=rows=>{const denom=sum(rows,'size');return denom?sum(rows,'active_customers')/denom:null;};
 $('cohort-kpis').innerHTML=[kpi('Идентифицированные покупатели',number(sum(base,'size')),'По положительным покупкам в окне'),kpi('Взвешенное M1',pct(weighted(m1)),number(m1.length)+' зрелых когорт',true),kpi('Взвешенное M3',pct(weighted(m3)),number(m3.length)+' зрелых когорт'),kpi('Когорт в истории',number(cohorts.length),'Первая наблюдаемая покупка')].join('');
 $('cohort-head').innerHTML='<tr><th>Когорта</th><th>Клиенты</th>'+Array.from({length:12},(_,i)=>`<th>M${i}</th>`).join('')+'</tr>';
 $('cohort-table').innerHTML=cohorts.map(c=>{const rows=data.cohorts.filter(r=>r.cohort===c),size=rows[0]?.size;return `<tr><td>${monthName(c)}</td><td>${number(size)}</td>`+Array.from({length:12},(_,i)=>{const r=rows.find(x=>x.age===i);if(!r||r.retention===null)return '<td style="background:#f1f4f6;color:#9aabb8" title="Следующий период не завершён">—</td>';const value=Number(r.retention);const l=96-value*59;return `<td style="background:hsl(174 38% ${l}%);color:${value>.55?'white':'#244c4b'}" title="${number(r.active_customers)} из ${number(size)} клиентов">${number(value*100)}%</td>`;}).join('')+'</tr>';}).join('');
}
function renderForecast(){
 const selected=forecast.models.find(m=>m.id===forecast.recommended_id)||forecast.models[0];
 $('forecast-kpis').innerHTML=[kpi('Стратегия по backtest',selected.label,'Выбрана на тех же проверочных месяцах',true),kpi('Прогноз · декабрь 2011',pounds(selected.forecast_gbp*100),'Ориентир планирования, не факт'),kpi('Средняя абсолютная ошибка',pounds(selected.mae_gbp*100),'На шести шагах проверки'),kpi('WAPE выбранной стратегии',pct(selected.wape),'Не независимая оценка после выбора')].join('');
 const colors=['#0f847c','#9b73ab','#d19455'];
 const series=[{label:'Факт',color:'#203b57',width:3,values:forecast.backtest.map(r=>r.actual_gbp)},...forecast.models.map((m,i)=>({label:m.label,color:colors[i],dash:true,values:forecast.backtest.map(r=>r.predictions[m.id])}))];
 $('forecast-chart').innerHTML=svgLineChart(forecast.backtest.map(r=>r.month),series,{height:300});
 $('forecast-legend').innerHTML=series.map(s=>`<span><i style="--color:${s.color}"></i>${esc(s.label)}</span>`).join('');
 $('forecast-models').innerHTML=forecast.models.map(m=>`<tr class="${m.id===selected.id?'model-selected':''}"><td>${esc(m.label)}${m.id===selected.id?' ✓':''}</td><td>${number(m.mae_gbp)}</td><td>${pct(m.wape)}</td><td>${number(m.forecast_gbp)}</td></tr>`).join('');
 $('forecast-limits').innerHTML=`<p><b>${esc(forecast.recommendation_label||'Сравнение прозрачных базовых стратегий')}</b></p><p>Модель выбрана по ошибке на тех же шести месяцах. Это сравнение кандидатов; для независимой оценки выбранной стратегии нужен новый период.</p><p>Короткая история и сезонность ограничивают надёжность. Интервал будущего значения не заявляется: шести ошибок недостаточно для убедительной калибровки.</p>`;
 $('backtest-head').innerHTML='<tr><th>Месяц</th><th>Факт, £</th>'+forecast.models.map(m=>`<th>${esc(m.label)}, £</th>`).join('')+'</tr>';
 $('backtest-table').innerHTML=forecast.backtest.map(r=>`<tr><td>${monthName(r.month)}</td><td>${number(r.actual_gbp)}</td>`+forecast.models.map(m=>`<td title="Ошибка факт − прогноз: ${number(r.actual_gbp-r.predictions[m.id])} GBP">${number(r.predictions[m.id])}</td>`).join('')+'</tr>').join('');
}
function renderQuality(){
 const q=data.quality,meta=data.meta;
 $('quality-kpis').innerHTML=[kpi('Исходные строки',number(meta.source_rows),'Оба листа официального XLSX'),kpi('Принято после правил',number(meta.accepted_rows),'Политика периодов и проверка операций',true),kpi('Строки без CustomerID',pct(q.missing_customer_share),number(q.missing_customer_rows)+' строк; охват — в методике'),kpi('Проверки ядра',number(data.checks.passed)+' / '+number(data.checks.passed+data.checks.failed),'Пройдены / выполнены')].join('');
 $('missing-chart').innerHTML=svgLineChart(q.monthly.map(r=>r.month),[{label:'Строки без CustomerID',color:'#0f847c',values:q.monthly.map(r=>r.rows?r.missing_customer_rows/r.rows*100:0)}],{money:false,height:260});
 const ruleNames={overlap_superseded_by_second_sheet:'Межлистовое перекрытие: оставлен второй лист',accepted:'Принято после правил качества',invalid_datetime:'Некорректная дата',invalid_or_zero_quantity:'Некорректное или нулевое количество',nonpositive_or_invalid_price:'Цена неположительная или некорректная',missing_invoice:'Отсутствует номер заказа',sign_prefix_mismatch:'Знак количества не соответствует коду отмены'};
 $('quality-rules').innerHTML=q.rules.map(r=>`<div class="quality-rule"><span>${esc(ruleNames[r.rule]||r.rule)}</span><b>${number(r.rows)}</b></div>`).join('');
 const checks=Array.isArray(validation.reconciliation_checks)?validation.reconciliation_checks:(Array.isArray(validation.checks)?validation.checks:(Array.isArray(validation.tests)?validation.tests:[]));
 $('test-summary').innerHTML=`<span class="badge">${number(data.checks.passed)} проверок пройдено</span> <span class="caption">Источник, SQL / pandas, суммы, окна и граничные случаи.</span>`;
 $('test-list').innerHTML=checks.map(r=>`<div class="test-row"><span class="test-check${r.passed===false?' test-fail':''}">${r.passed===false?'×':'✓'}</span><span>${esc(r.check||r.name||r.test||JSON.stringify(r))}</span></div>`).join('')+(validation.fixture_tests_passed?`<div class="test-row"><span class="test-check">✓</span><span>${number(validation.fixture_tests_passed)} отдельных тестов граничных случаев: <a href="tests/test_engine.py">исходный код тестов</a>.</span></div>`:'');
 $('duplicate-impact').textContent=`Точных повторов по принятой политике: ${number(q.exact_duplicate_rows)}. Разница оборота после отмен при их удалении: ${pounds(q.duplicate_net_sensitivity_pence)}. Межлистовое перекрытие обрабатывается отдельно и не приравнивается к неоднозначным повторам внутри периода.`;
 $('source-sha').textContent=meta.source_sha256;
}
function downloadCSV(rows,columns,filename){
 // Protect spreadsheet consumers from formula injection in text cells.
 const value=v=>{let s=String(v??'');if(typeof v==='string'&&/^[=+@\-]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};
 const text='\uFEFF'+[columns.map(value).join(','),...rows.map(r=>columns.map(c=>value(r[c])).join(','))].join('\r\n');
 const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function init(){
 try {
  const urls=['results/dashboard.json','results/forecast.json','results/validation.json'];
  [data,forecast,validation]=await Promise.all(urls.map(async url=>{const response=await fetch(url);if(!response.ok)throw new Error(url+' · HTTP '+response.status);return response.json();}));
  if(!data.meta?.months?.length||!data.monthly?.length||!forecast.models?.length)throw new Error('Неполный набор агрегатов');
  $('source-count').textContent=number(data.meta.source_rows);
  $('country').innerHTML='<option value="all">Все страны</option>'+data.meta.countries.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');
  ['from','to'].forEach(id=>$(id).innerHTML=data.meta.months.map(m=>`<option value="${m}">${monthName(m)}</option>`).join(''));
  $('from').value=data.meta.months[0];$('to').value=data.meta.months.at(-1);
  ['country','from','to'].forEach(id=>$(id).addEventListener('change',renderOverview));
  $('reset-filters').addEventListener('click',()=>{$('country').value='all';$('from').value=data.meta.months[0];$('to').value=data.meta.months.at(-1);renderOverview();});
  $('export-sales').addEventListener('click',()=>downloadCSV(filteredSales(),['month','country','gross_pence','cancel_pence','net_pence','orders'],'commerce_sales_pence.csv'));
  ['product-search','abc-filter','product-sort'].forEach(id=>$(id).addEventListener(id==='product-search'?'input':'change',()=>{productPage=0;renderProducts();}));
  $('products-prev').addEventListener('click',()=>{productPage--;renderProducts();});$('products-next').addEventListener('click',()=>{productPage++;renderProducts();});
  $('export-products').addEventListener('click',()=>downloadCSV(currentProducts,['stock_code','description','code_category','abc','gross_pence','cancel_pence','net_pence','quantity','orders'],'commerce_products_pence.csv'));
  renderOverview();renderInsights();renderProductSummary();renderProducts();renderCohorts();renderForecast();renderQuality();$('load-status').hidden=true;
 } catch(error){$('load-status').textContent='Не удалось загрузить расчёты. Откройте страницу через веб-сервер или воспользуйтесь архивом проекта. '+error.message;$('load-status').classList.add('error');}
}
document.querySelectorAll('nav [data-page]').forEach(button=>button.addEventListener('click',()=>setPage(button.dataset.page)));
window.addEventListener('hashchange',()=>setPage(location.hash.slice(1),false));
setPage(location.hash.slice(1)||'overview',false);init();
