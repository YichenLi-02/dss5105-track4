/* UI-only scheduling simulator. Replace with member 4/5 services for integration. */
(function(global){
 const toMs=value=>{value=String(value||'').replace(' ','T');return Date.parse(value.length===16?value+':00+08:00':value);};
 const iso=ms=>new Date(ms+8*3600000).toISOString().slice(0,16);
 const day=ms=>iso(ms).slice(0,10);
 const overlap=(a,b)=>a.start<b.end&&b.start<a.end;
 function generate(tasks,availability,busy,locked=[],settings={},completed=[]){
  const now=toMs(settings.now||'2026-10-12T08:00'),cap=Number(settings.dailyMinutes||180),buffer=Number(settings.bufferHours??24)*3600000;
  const occupied=busy.map(s=>({start:toMs(s.start),end:toMs(s.end)})),blocks=[],warnings=[],unscheduled=[],daily={};
  const valid=tasks.filter(t=>t.confirmed&&t.due&&Number(t.effort)>0);
  tasks.filter(t=>!valid.includes(t)&&!(t.confirmed&&Number(t.effort)===0)).forEach(t=>warnings.push({task:t.id,code:'NEEDS_INPUT',message:t.title+': confirm a deadline and remaining effort.'}));
  completed.forEach(b=>{const start=toMs(b.start),end=toMs(b.end);daily[day(start)]=(daily[day(start)]||0)+(end-start)/60000;occupied.push({start,end});});
  const activeIds=new Set(valid.map(t=>t.id));
  let lockConflict=false;
  locked.filter(b=>!activeIds.has(b.taskId)).forEach(b=>{lockConflict=true;warnings.push({task:b.taskId,code:'LOCK_CONFLICT',message:'Confirm the changed task before re-planning its locked session.'});});
  locked.filter(b=>activeIds.has(b.taskId)).forEach(b=>{
   const n={...b,start:toMs(b.start),end:toMs(b.end),locked:true};const task=valid.find(t=>t.id===b.taskId);const length=(n.end-n.start)/60000;
   const available=availability.some(s=>n.start>=toMs(s.start)&&n.end<=toMs(s.end));
   const permitted=iso(n.start).slice(11)>='09:00'&&iso(n.end).slice(11)<='22:00'&&day(n.start)===day(n.end);
   if(n.start<now||n.end>toMs(task.due)||length<=0||length>90||!available||!permitted||occupied.some(o=>overlap(n,o))||blocks.some(o=>overlap(n,o))||(daily[day(n.start)]||0)+length>cap){lockConflict=true;warnings.push({task:b.taskId,code:'LOCK_CONFLICT',message:'A locked session conflicts with the current inputs. Unlock or edit it first.'});}
   blocks.push(n);daily[day(n.start)]=(daily[day(n.start)]||0)+length;
  });
  if(lockConflict)return {blocks:blocks.map(b=>({...b,start:iso(b.start),end:iso(b.end)})),warnings,unscheduled:[],blocked:true};
  const ranges=availability.map(s=>({start:toMs(s.start),end:toMs(s.end)})).sort((a,b)=>a.start-b.start);
  valid.sort((a,b)=>toMs(a.due)-toMs(b.due)||({high:0,medium:1,low:2}[a.priority]-{high:0,medium:1,low:2}[b.priority])||a.id.localeCompare(b.id)).forEach(task=>{
   const rounded=Math.max(30,Math.ceil(Number(task.effort)*60/15)*15);
   if(rounded!==Number(task.effort)*60)warnings.push({task:task.id,code:'EFFORT_ROUNDED',message:task.title+': '+rounded+' minutes reserved from '+(Number(task.effort)*60)+' estimated minutes.'});
   let remaining=rounded-blocks.filter(b=>b.taskId===task.id).reduce((n,b)=>n+(b.end-b.start)/60000,0);
   if(remaining<0){warnings.push({task:task.id,code:'LOCK_EXCEEDS_EFFORT',message:task.title+': locked time exceeds remaining effort.'});lockConflict=true;return;}
   const due=toMs(task.due);
   if(due<=now){warnings.push({task:task.id,code:'PAST_DEADLINE',message:task.title+': deadline already passed. Review it without automatically shifting the date.'});unscheduled.push({taskId:task.id,minutes:remaining});return;}
   for(const limit of [due-buffer,due]){for(const range of ranges){
    for(let at=Math.ceil(Math.max(now,range.start)/900000)*900000;at<Math.min(range.end,limit)&&remaining>0;at+=900000){
     const date=day(at),hour=iso(at).slice(11);if(hour<'09:00'||hour>='22:00'||(daily[date]||0)>=cap)continue;
     let minutes=Math.min(90,remaining,cap-(daily[date]||0));minutes=Math.floor(minutes/15)*15;
     while(minutes>=30){if(remaining-minutes===15){minutes-=15;continue;}const test={start:at,end:at+minutes*60000};const busyConflict=occupied.some(b=>overlap(test,b));const sessionConflict=[...blocks,...completed.map(b=>({...b,start:toMs(b.start),end:toMs(b.end)}))].some(b=>test.start<b.end+900000&&b.start<test.end+900000);
      if(test.end<=range.end&&test.end<=limit&&iso(test.end).slice(11)<='22:00'&&day(test.end)===date&&!busyConflict&&!sessionConflict){blocks.push({...test,taskId:task.id,locked:false});daily[date]=(daily[date]||0)+minutes;remaining-=minutes;at=test.end-900000;break;}minutes-=15;
     }
    }
   }if(!remaining)break;}
   if(remaining>0)unscheduled.push({taskId:task.id,minutes:remaining});
   const taskBlocks=blocks.filter(b=>b.taskId===task.id);if(taskBlocks.length&&remaining===0&&due-Math.max(...taskBlocks.map(b=>b.end))<buffer)warnings.push({task:task.id,code:'LOW_BUFFER',message:task.title+': less than '+(buffer/3600000)+' hours before its deadline.'});
  });
  return {blocks:blocks.sort((a,b)=>a.start-b.start).map(b=>({...b,start:iso(b.start),end:iso(b.end)})),warnings,unscheduled,blocked:lockConflict};
 }
 global.StudyPlanner={generate,toMs,iso};
})(typeof window==='undefined'?globalThis:window);
