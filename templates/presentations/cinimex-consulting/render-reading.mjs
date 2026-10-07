import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {fileURLToPath, pathToFileURL} from 'node:url';

const args=Object.fromEntries(process.argv.slice(2).filter((v,i,a)=>v.startsWith('--')&&v!=='--plan').map(v=>[v.slice(2),process.argv[process.argv.indexOf(v)+1]]));
const workspace=path.resolve(args.workspace);
const root=path.resolve(args.root??path.join(path.dirname(fileURLToPath(import.meta.url)),'../../..'));
const out=path.resolve(args.out);
const preview=out.replace(/\.pptx$/, '-preview');
const data=JSON.parse(await fs.readFile(path.resolve(args.input),'utf8'));
const diagrams=JSON.parse(await fs.readFile(path.resolve(args.diagrams),'utf8'));
const coverAsset=path.resolve(root,data.slides[0].cover_image);
const coverImage=await fs.readFile(coverAsset);
const coverPrompt=await fs.readFile(coverAsset.replace(/\.[^.]+$/,'.prompt.json'),'utf8').then(v=>JSON.parse(v).prompt,()=>undefined);
const inventory = (await fs.readFile(path.join(workspace,'template-inspect/template-inspect.ndjson'),'utf8')).trim().split('\n').map(JSON.parse);
const layoutFor = part => part.layout;
const visualLayouts=['work-comparison','context-diptych','annotated-choice','catalog-anatomy','answer-evidence','options-table','value-tree','acceptance-cases'];
const map = { outputSlides:data.slides.map(part => ({
  outputSlide:part.number, sourceSlide:part.number===1?1:2, narrativeRole:part.kicker,
  reuseMode:'duplicate-slide',
  editTargets:inventory.filter(e=>e.slide===(part.number===1?1:2)&&e.kind==='textbox').map(e=>({
    sourceElementId:e.id, action:(part.number===1?['Rectangle 8','Rectangle 10','Rectangle 12','Rectangle 14']:
      ['Rectangle 13','Rectangle 19','Rectangle 25',...(!['timeline','company'].includes(layoutFor(part))?['Rectangle 10','Rectangle 16','Rectangle 22']:[]),
        ...(['matrix','method-table','diagram','source-image','gates','contents','executive-summary','section-intro',...visualLayouts].includes(layoutFor(part))?['Rectangle 11','Rectangle 14','Rectangle 17','Rectangle 20','Rectangle 23','Rectangle 26']:[])])
      .includes(e.name)?'delete':e.name==='Rectangle 8'?'keep':'rewrite-and-reposition',
    reason:'Более содержательная версия для самостоятельного чтения; пользователь разрешил изменить структуру.'
  })),
})), omittedSourceSlides:[] };
for(const item of map.outputSlides) {
  const slide=item.sourceSlide;
  const part=data.slides[item.outputSlide-1];
  const dropped=slide===1?['Oval 5','Oval 6','Oval 7','Rounded Rectangle 9','Rounded Rectangle 11','Rounded Rectangle 13']:
    ['Rounded Rectangle 12','Rounded Rectangle 18','Rounded Rectangle 24','Straight Connector 7','Straight Connector 8',
      ...(layoutFor(part)==='timeline'?[]:['Oval 9','Oval 15','Oval 21'])];
  for(const e of inventory.filter(e=>e.slide===slide && e.kind==='shape' && dropped.includes(e.name))) {
    item.editTargets.push({sourceElementId:e.id,action:'delete',reason:'Освободить место для развёрнутого текста и сравнения.'});
  }
  if(slide===1)item.editTargets.push({action:'add',newPrimitiveAllowed:true,zone:{left:790,top:108,width:430,height:355},reason:'Пользователь запросил заменить круги иллюстрацией каталога и консультации.',mustNotOverlapInherited:true});
  item.editTargets.push({action:'add',newPrimitiveAllowed:true,zone:{left:72,top:688,width:1136,height:22},
    reason:'Читаемая подпись источника для клиентского документа.',mustNotOverlapInherited:true});
  if(['matrix','method-table','diagram','source-image','gates','contents','executive-summary','section-intro',...visualLayouts].includes(layoutFor(data.slides[item.outputSlide-1]))) item.editTargets.push({action:'add',newPrimitiveAllowed:true,
    zone:{left:72,top:170,width:1136,height:438},reason:'Редактируемая композиция сравнения, результата или оснований; пользователь утвердил визуальную переработку.',mustNotOverlapInherited:true});
}
await fs.writeFile(path.join(workspace,'reading-frame-map.json'),JSON.stringify(map,null,2));
if(process.argv.includes('--plan')) { console.log(JSON.stringify({map:path.join(workspace,'reading-frame-map.json'),slides:data.slides.length})); process.exit(0); }

const runtime=process.env.CINIMEX_ARTIFACT_TOOL??path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool');
const entry=path.join(runtime,'dist/artifact_tool.mjs');
const {PresentationFile,FileBlob}=await import(pathToFileURL(entry).href);
const {Canvas,loadImage}=createRequire(entry)('skia-canvas');
const context=new Canvas(1,1).getContext('2d');
const p=await PresentationFile.importPptx(await FileBlob.load(path.join(workspace,'reading-starter.pptx')));
const C={navy:'#071D33',orange:'#F28A20',muted:'#536777',paper:'#F4F7FA',grid:'#E5EBEF',white:'#FFFFFF'};
const bodySize=19;
const checks=[];
function wrap(value,width,size,bold=false){
  context.font=`${bold?'bold ':''}${size}px Calibri`;
  const lines=[];
  for(const paragraph of String(value).split('\n')) {
    let line='';
    for(const word of paragraph.split(/\s+/).filter(Boolean)) {
      const next=line?`${line} ${word}`:word;
      if(context.measureText(next).width>width*0.93 && line){lines.push(line);line=word;}
      else line=next;
    }
    lines.push(line);
  }
  return lines;
}
function get(slide,name){const s=slide.shapes.items.find(s=>s.name===name);if(!s)throw Error(`Missing ${name}`);return s;}
function remove(slide,names){for(const name of names){const s=slide.shapes.items.find(s=>s.name===name);if(s)slide.shapes.deleteById(s.id);}}
function text(slide,name,value,x,y,w,h,size=bodySize,color=C.navy,bold=false,align='left'){
  const s=get(slide,name); const lines=wrap(value,w,size,bold);
  if(lines.length*size*1.23>h+6)throw Error(`Slide ${slideIndex+1} ${name}: ${lines.length} lines > height ${h}: ${value}`);
  s.position={left:x,top:y,width:w,height:h}; s.text=lines.join('\n');
  s.text.style={fontSize:size,typeface:'Calibri',color,bold,alignment:align,verticalAlignment:'top',wrap:'square',autoFit:'none',lineSpacing:visualLayouts.includes(data.slides[slideIndex].layout)?1:1.15,insets:{left:0,right:0,top:0,bottom:0}};
  checks.push({slide:slideIndex+1,name,lines:lines.length,fontSize:size,bounds:[x,y,w,h]}); return s;
}
const titleNames=['Rectangle 11','Rectangle 17','Rectangle 23'];
const bodyNames=['Rectangle 14','Rectangle 20','Rectangle 26'];
const numberNames=['Rectangle 10','Rectangle 16','Rectangle 22'];
function clearBody(slide,keepNumbers=false){
  remove(slide,['Rounded Rectangle 12','Rounded Rectangle 18','Rounded Rectangle 24','Rectangle 13','Rectangle 19','Rectangle 25','Straight Connector 7','Straight Connector 8']);
  if(!keepNumbers) remove(slide,['Oval 9','Oval 15','Oval 21',...numberNames]);
}
function columns(slide,part,flow=false,company=false){
  clearBody(slide,flow||company);
  const xs=[72,438,804],w=340;
  if(company){
    remove(slide,['Oval 9','Oval 15','Oval 21']);
    const year=data.company.facts.find(f=>f.id==='founded').value.match(/\d{4}/)[0];
    const headcount=data.company.facts.find(f=>f.id==='headcount').value.replace(/^около\s+/,'~');
    for(let i=0;i<3;i++)text(slide,numberNames[i],[`${year} · ${headcount}`,'Знания + 1С','Интеграции + ИИ'][i],xs[i],175,w,51,i===0?22:30,C.orange,true);
  }
  for(let i=0;i<part.blocks.length;i++){
    const b=part.blocks[i];
    if(flow&&!company) {get(slide,['Oval 9','Oval 15','Oval 21'][i]).position={left:xs[i],top:184,width:50,height:50};text(slide,numberNames[i],`0${i+1}`,xs[i]+4,191,42,34,23,C.white,true,'center');}
    const top=flow?253:company?230:190;
    text(slide,titleNames[i],b.heading.replace(/^\d\.\s*/,''),xs[i],top,w,company?63:73,24,C.navy,true);
    const bodyTop=top+(company?74:83);
    text(slide,bodyNames[i],b.body,xs[i],bodyTop,w,594-bodyTop,bodySize,C.muted);
  }
}
function comparison(slide,part,scenario=false){
  clearBody(slide);
  const xs=[72,662],ws=[542,542];
  for(let i=0;i<2;i++){
    text(slide,titleNames[i],part.blocks[i].heading,xs[i],190,ws[i],77,24,C.navy,true);
    const bodyHeight=scenario?(i===1?170:315):220;
    text(slide,bodyNames[i],part.blocks[i].body,xs[i],277,ws[i],bodyHeight,bodySize,C.muted);
  }
  const b=part.blocks[2];
  if(scenario){text(slide,titleNames[2],b.heading,662,457,542,31,22,C.navy,true);text(slide,bodyNames[2],b.body,662,490,542,104,bodySize,C.muted);}
  else{text(slide,titleNames[2],b.heading,72,508,280,67,22,C.navy,true);text(slide,bodyNames[2],b.body,370,508,834,86,bodySize,C.muted);}
}
function rows(slide,part){
  clearBody(slide);
  const heights=part.blocks.map(b=>Math.max(71,wrap(b.body,818,bodySize).length*bodySize*1.23+4));
  if(heights.reduce((a,b)=>a+b,0)+16>407)throw Error(`Rows do not fit slide ${slideIndex+1}: ${heights}`);
  let y=186;
  part.blocks.forEach((b,i)=>{text(slide,titleNames[i],b.heading,72,y,276,heights[i],23,C.navy,true);text(slide,bodyNames[i],b.body,388,y,818,heights[i],bodySize,C.muted);y+=heights[i]+8;});
}
function matrix(slide,part,method=false){
  clearBody(slide);remove(slide,[...titleNames,...bodyNames]);
  const compact=method||part.blocks.length>=4;
  const size=compact?17:18.5,w=828,padding=method?11:compact?10:18,header=method?36:40;
  const rowHeights=part.blocks.map(b=>Math.max(wrap(b.heading,278,size,true).length*size*1.28,wrap(b.body,w,size).length*size*1.28)+padding);
  const height=header+rowHeights.reduce((a,b)=>a+b,0);
  if(height>435)throw Error(`Matrix does not fit slide ${slideIndex+1}: ${height}`);
  const values=[part.table_headers??[method?'Шаг методики':'Ситуация / вопрос',method?'Содержание работы':'Предлагаемый подход'],...part.blocks.map(b=>[wrap(b.heading,278,size,true).join('\n'),wrap(b.body,w,size).join('\n')])];
  const t=slide.tables.add({rows:values.length,columns:2,left:72,top:height>407?172:186,width:1136,height,columnWidths:[300,836],values});
  t.borders.assign({style:'solid',fill:C.grid,width:0.7});
  t.cells.block({row:0,column:0,rowCount:values.length,columnCount:2}).assign({fill:C.paper,textStyle:{typeface:'Calibri',fontSize:size,color:C.navy},margins:{left:11,right:11,top:padding/2,bottom:padding/2},anchor:'top'});
  t.rows[0].height=header;
  for(let c=0;c<2;c++){t.getCell(0,c).fill=C.navy;t.getCell(0,c).text.style={fontSize:19,typeface:'Calibri',bold:true,color:C.white};}
  for(let r=1;r<values.length;r++){t.rows[r].height=rowHeights[r-1];for(let c=0;c<2;c++)t.getCell(r,c).fill=r%2?C.paper:C.white;t.getCell(r,0).text.style={fontSize:size,typeface:'Calibri',bold:true,color:C.navy};}
}
function addText(slide,name,value,x,y,w,h,size=19,color=C.navy,bold=false){
  slide.shapes.add({geometry:'textbox',name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  return text(slide,name,value,x,y,w,h,size,color,bold);
}
function contents(slide,part){
  clearBody(slide);remove(slide,[...titleNames,...bodyNames]);
  const pageLabel=index=>{
    const range=part.contents_ranges[index];
    return `${String(range.start).padStart(2,'0')}${range.end===range.start?'':`–${String(range.end).padStart(2,'0')}`}`;
  };
  addText(slide,'contents-summary-title',part.blocks[0].heading,72,184,960,34,24,C.navy,true);
  addText(slide,'contents-summary-body',part.blocks[0].body,72,222,960,28,19,C.muted);
  addText(slide,'contents-summary-page',pageLabel(0),1110,184,98,34,25,C.orange,true);
  route(slide,'contents-rule',[[72,269],[1208,269]],false,false,'#BECAD5');
  for(let i=1;i<part.blocks.length;i++){
    const b=part.blocks[i],column=i<=3?0:1,row=(i-1)%3,x=column?662:72,y=290+row*100;
    addText(slide,`contents-number-${i}`,String(i).padStart(2,'0'),x,y+2,40,29,18,C.orange,true);
    addText(slide,`contents-title-${i}`,b.heading,x+49,y,360,58,22,C.navy,true);
    addText(slide,`contents-pages-${i}`,pageLabel(i),x+436,y,106,32,22,C.orange,true);
    addText(slide,`contents-body-${i}`,b.body,x+49,y+59,491,39,17,C.muted);
  }
}
function executiveSummary(slide,part){
  clearBody(slide);remove(slide,[...titleNames,...bodyNames]);
  slide.shapes.add({geometry:'rect',name:'summary-proposal-background',position:{left:72,top:181,width:352,height:415},fill:C.navy,line:{fill:'none',width:0}});
  addText(slide,'summary-proposal-label','ПРЕДЛОЖЕНИЕ СИНИМЕКС',92,202,310,24,14,C.orange,true);
  addText(slide,'summary-proposal-title',part.blocks[0].heading,92,242,310,102,30,C.white,true);
  addText(slide,'summary-proposal-body',part.blocks[0].body,92,354,310,224,19,'#D9E7F3');
  for(let i=1;i<part.blocks.length;i++){
    const b=part.blocks[i],y=184+(i-1)*136;
    addText(slide,`summary-heading-${i}`,b.heading,472,y,736,35,24,C.navy,true);
    addText(slide,`summary-body-${i}`,b.body,472,y+42,736,98,19,C.muted);
    if(i<part.blocks.length-1)route(slide,`summary-rule-${i}`,[[472,y+127],[1208,y+127]],false,false,'#BECAD5');
  }
}
function sectionIntro(slide,part){
  clearBody(slide);remove(slide,[...titleNames,...bodyNames]);
  slide.shapes.add({geometry:'rect',name:'section-banner',position:{left:72,top:184,width:1136,height:106},fill:C.navy,line:{fill:'none',width:0}});
  addText(slide,'section-number',String(part.section_number).padStart(2,'0'),92,207,92,63,48,C.orange,true);
  addText(slide,'section-label',part.section_label,211,218,963,57,30,C.white,true);
  addText(slide,'section-task-heading',part.blocks[0].heading,72,322,542,38,24,C.navy,true);
  addText(slide,'section-task-body',part.blocks[0].body,72,369,542,233,19,C.muted);
  addText(slide,'section-known-heading',part.blocks[1].heading,662,322,542,38,24,C.navy,true);
  addText(slide,'section-known-body',part.blocks[1].body,662,369,542,91,19,C.muted);
  addText(slide,'section-open-heading',part.blocks[2].heading,662,480,542,34,24,C.navy,true);
  addText(slide,'section-open-body',part.blocks[2].body,662,519,542,87,19,C.muted);
}
function visualBody(slide){clearBody(slide);remove(slide,[...titleNames,...bodyNames]);}
function rect(slide,name,x,y,w,h,fill=C.paper,line='none'){
  return slide.shapes.add({geometry:'rect',name,position:{left:x,top:y,width:w,height:h},fill,line:{fill:line,width:line==='none'?0:0.8}});
}
function nativeTable(slide,name,values,x,y,widths,{size=17,header=35,minRow=42,maxHeight=300,emphasis=[]}={}){
  const heights=values.slice(1).map(row=>Math.max(minRow,...row.map((v,c)=>wrap(v,widths[c]-22,size,c===0).length*size*1.22+14)));
  const h=header+heights.reduce((a,b)=>a+b,0);
  if(h>maxHeight)throw Error(`Slide ${slideIndex+1} ${name}: table height ${h} > ${maxHeight}`);
  const copy=values.map((row,r)=>row.map((v,c)=>wrap(v,widths[c]-22,r?size:18,c===0||!r).join('\n')));
  const t=slide.tables.add({name,rows:values.length,columns:widths.length,left:x,top:y,width:widths.reduce((a,b)=>a+b,0),height:h,columnWidths:widths,values:copy});
  t.cells.block({row:0,column:0,rowCount:values.length,columnCount:widths.length}).assign({fill:C.white,textStyle:{typeface:'Calibri',fontSize:size,color:C.navy},margins:{left:10,right:10,top:7,bottom:6},anchor:'top'});
  t.rows[0].height=header;
  for(let r=0;r<values.length;r++)for(let c=0;c<widths.length;c++){
    const cell=t.getCell(r,c);
    if(r)t.rows[r].height=heights[r-1];
    cell.fill=r===0?C.navy:r%2?C.white:C.paper;
    cell.text.style={fontSize:r?size:18,typeface:'Calibri',bold:r===0||c===0,color:r?C.navy:C.white,lineSpacing:1.04};
  }
  for(const [r,c]of emphasis){t.getCell(r,c).fill='#FCE9D8';t.getCell(r,c).text.style={fontSize:size,typeface:'Calibri',bold:true,color:'#9B4F10',lineSpacing:1.04};}
  t.borders.assign({fill:'#D9E2EA',width:0.7,style:'solid'});
  return h;
}
function workComparison(slide,part){
  visualBody(slide);const v=part.visual_copy;
  addText(slide,'work-caption',v.caption,72,178,1136,27,17,C.muted);
  const xs=[332,551,770,989],w=205;
  for(let j=0;j<4;j++)addText(slide,`work-criterion-${j}`,v.criteria[j],xs[j],207,w,66,19,C.navy,true);
  part.blocks.forEach((b,i)=>{
    const y=274+i*166;
    rect(slide,`work-band-${i}`,72,y,1136,154,i?'#EDF2F6':C.white);
    addText(slide,`work-heading-${i}`,b.heading,88,y+13,217,118,22,i?'#9B4F10':C.navy,true);
    const items=i?v.proposed:v.baseline;
    items.forEach((value,j)=>addText(slide,`work-step-${i}-${j}`,value,xs[j],y+9,w,78,19,C.navy));
    addText(slide,`work-explanation-${i}`,b.body,332,y+89,860,65,17,C.muted);
  });
}
async function contextDiptych(slide,part){
  visualBody(slide);const v=part.visual_copy,bytes=await fs.readFile(path.resolve(root,part.image_path));
  for(let i=0;i<2;i++)addText(slide,`context-heading-${i}`,part.blocks[i].heading,[72,662][i],179,546,31,22,C.navy,true);
  slide.images.add({blob:bytes,contentType:'image/png',alt:v.image_caption,fit:'cover',position:{left:72,top:218,width:1136,height:177}});
  addText(slide,'context-image-caption',v.image_caption,72,401,1136,20,12.5,C.muted);
  for(let i=0;i<2;i++){
    const x=[72,662][i];
    addText(slide,`context-question-${i}`,v.questions[i],x,431,546,34,22,C.navy,true);
    addText(slide,`context-body-${i}`,part.blocks[i].body,x,465,546,105,18,C.muted);
  }
  addText(slide,'context-common-heading',part.blocks[2].heading,72,580,248,28,18,C.navy,true);
  addText(slide,'context-common-body',part.blocks[2].body,332,575,876,36,17,C.muted);
}
function annotatedChoice(slide,part){
  visualBody(slide);const v=part.visual_copy;
  rect(slide,'choice-rule-1',958,325,22,2,C.orange);
  rect(slide,'choice-rule-2',958,444,22,2,C.orange);
  rect(slide,'choice-sheet',351,178,608,425,'none','#D9E2EA');
  rect(slide,'choice-sheet-top',351,178,608,4,C.navy);
  addText(slide,'choice-visitor-heading',part.blocks[0].heading,72,188,257,69,23,C.navy,true);
  addText(slide,'choice-visitor-body',part.blocks[0].body,72,270,257,330,18,C.muted);
  addText(slide,'choice-result-heading',part.blocks[1].heading,371,190,568,34,24,C.navy,true);
  addText(slide,'choice-result-body',part.blocks[1].body,371,228,568,67,18,C.navy);
  addText(slide,'choice-caption',v.caption,371,299,568,25,17,C.muted);
  const h=nativeTable(slide,'choice-comparison',[v.headers,...v.rows],371,332,[210,179,179],{size:17,header:34,minRow:42,maxHeight:165,emphasis:[[2,2]]});
  addText(slide,'choice-status',v.status_note,371,332+h+12,568,45,18,C.navy,true);
  addText(slide,'choice-sources',v.sources_note,371,557,568,45,17,C.muted);
  addText(slide,'choice-annotation-heading',part.blocks[2].heading,994,247,214,88,22,'#9B4F10',true);
  addText(slide,'choice-annotation-body',part.blocks[2].body,994,340,214,263,18,C.muted);
}
function catalogAnatomy(slide,part){
  visualBody(slide);const v=part.visual_copy;
  addText(slide,'catalog-caption',v.caption,72,178,670,42,18,C.navy,true);
  nativeTable(slide,'catalog-record',[['Поле записи','Какое решение помогает проверить'],...v.fields],72,235,[233,469],{size:18,header:45,minRow:70,maxHeight:342});
  part.blocks.forEach((b,i)=>{
    const y=[178,320,450][i];
    addText(slide,`catalog-heading-${i}`,b.heading,816,y,392,32,22,C.navy,true);
    addText(slide,`catalog-body-${i}`,b.body,816,y+40,392,i===0?100:85,17,C.muted);
  });
  addText(slide,'catalog-status',v.status_note,72,576,1136,32,17,'#9B4F10',true);
}
function answerEvidence(slide,part){
  visualBody(slide);const v=part.visual_copy;
  const ys=[209,329,438];
  for(let i=0;i<3;i++)route(slide,`evidence-link-${i}`,[[574,ys[i]+44],[650,ys[i]+44]],false,true,i===2?C.orange:C.muted);
  addText(slide,'evidence-caption',v.caption,72,178,1136,28,17,C.muted);
  for(let i=0;i<3;i++){
    const b=part.blocks[i],y=ys[i];
    addText(slide,`evidence-source-heading-${i}`,b.heading,72,y,490,31,21,C.navy,true);
    addText(slide,`evidence-source-body-${i}`,b.body,72,y+35,490,i===0?78:69,17,C.muted);
    rect(slide,`evidence-answer-bg-${i}`,662,y,546,104,i===2?'#FCE9D8':C.white);
    addText(slide,`evidence-answer-${i}`,v.answer_lines[i],680,y+15,509,78,19,i===2?'#9B4F10':C.navy,true);
  }
  const b=part.blocks[3];
  route(slide,'evidence-role-rule',[[72,544],[1208,544]],false,false,'#BECAD5');
  addText(slide,'evidence-role-heading',b.heading,72,549,350,53,21,C.navy,true);
  addText(slide,'evidence-role-body',b.body,458,549,750,59,17,C.muted);
}
function optionsTable(slide,part){
  visualBody(slide);const v=part.visual_copy;
  addText(slide,'options-heading',part.blocks[0].heading,72,177,250,65,23,C.navy,true);
  addText(slide,'options-body',part.blocks[0].body,348,177,860,65,17,C.muted);
  addText(slide,'options-caption',v.caption,72,242,1136,25,17,'#9B4F10',true);
  const h=nativeTable(slide,'deployment-options',[v.headers,...v.rows],72,269,[216,307,307,306],{size:17,header:45,minRow:44,maxHeight:268});
  addText(slide,'options-next-heading',part.blocks[1].heading,72,269+h+14,250,57,21,C.navy,true);
  addText(slide,'options-next-body',part.blocks[1].body,348,269+h+14,860,57,17,C.muted);
}
function valueTree(slide,part){
  visualBody(slide);const v=part.visual_copy,xs=[72,458,844],w=364;
  for(let i=0;i<3;i++)route(slide,`value-branch-${i}`,[[640,272],[640,280],[xs[i]+w/2,280],[xs[i]+w/2,289]],false,false,'#BECAD5');
  addText(slide,'value-root-heading',v.root_heading,72,178,1136,35,25,C.navy,true);
  addText(slide,'value-root-body',v.root_body,72,217,1136,44,18,C.muted);
  part.blocks.forEach((b,i)=>{
    addText(slide,`value-heading-${i}`,b.heading,xs[i],295,w,31,23,C.navy,true);
    addText(slide,`value-body-${i}`,b.body,xs[i],331,w,146,17,C.muted);
  });
  route(slide,'value-baseline-rule',[[72,486],[1208,486]],false,false,'#BECAD5');
  for(const [i,prefix]of ['baseline','pilot'].entries()){
    const x=i?662:72;
    addText(slide,`value-${prefix}-heading`,v[`${prefix}_heading`],x,489,542,31,21,i?'#9B4F10':C.navy,true);
    addText(slide,`value-${prefix}-body`,v[`${prefix}_body`],x,522,542,64,17,C.muted);
  }
  addText(slide,'value-status',v.status_note,72,587,1136,21,17,C.muted);
}
function acceptanceCases(slide,part){
  visualBody(slide);const v=part.visual_copy;
  addText(slide,'acceptance-caption',v.caption,72,175,1136,28,17,C.muted);
  const h=nativeTable(slide,'acceptance-examples',[v.headers,...v.cases],72,207,[332,404,400],{size:17,header:37,minRow:71,maxHeight:263,emphasis:[[2,1],[3,1]]});
  const y=207+h+10;
  part.blocks.forEach((b,i)=>{
    const x=[72,458,844][i];
    addText(slide,`acceptance-heading-${i}`,b.heading,x,y,364,28,21,C.navy,true);
    addText(slide,`acceptance-body-${i}`,b.body,x,y+32,364,63,17,C.muted);
  });
  addText(slide,'acceptance-protocol-heading',v.protocol_heading,72,568,256,39,18,'#9B4F10',true);
  addText(slide,'acceptance-protocol-body',v.protocol_body,348,567,860,41,17,C.muted);
}
function route(slide,name,points,dashed=false,arrow=true,color=C.muted){
  const minX=Math.min(...points.map(p=>p[0])),minY=Math.min(...points.map(p=>p[1]));
  const w=Math.max(1,Math.max(...points.map(p=>p[0]))-minX),h=Math.max(1,Math.max(...points.map(p=>p[1]))-minY);
  slide.shapes.add({geometry:'custom',name,position:{left:minX,top:minY,width:w,height:h},fill:'none',line:{fill:color,width:2,style:dashed?'dash':'solid'},customPaths:[{width:w,height:h,commands:points.map((p,i)=>({[i?'lineTo':'moveTo']:{x:p[0]-minX,y:p[1]-minY}}))}]});
  if(arrow){
    const [x,y]=points.at(-1),[px,py]=points.at(-2),angle=Math.atan2(y-py,x-px),len=9,half=4;
    const vertices=[[x,y],[x-len*Math.cos(angle)+half*Math.sin(angle),y-len*Math.sin(angle)-half*Math.cos(angle)],[x-len*Math.cos(angle)-half*Math.sin(angle),y-len*Math.sin(angle)+half*Math.cos(angle)]];
    const ax=Math.min(...vertices.map(v=>v[0])),ay=Math.min(...vertices.map(v=>v[1]));
    const aw=Math.max(1,Math.max(...vertices.map(v=>v[0]))-ax),ah=Math.max(1,Math.max(...vertices.map(v=>v[1]))-ay);
    slide.shapes.add({geometry:'custom',name:`${name}-arrow`,position:{left:ax,top:ay,width:aw,height:ah},fill:color,line:{fill:color,width:0},customPaths:[{width:aw,height:ah,commands:[...vertices.map((v,i)=>({[i?'lineTo':'moveTo']:{x:v[0]-ax,y:v[1]-ay}})),{close:{}}]}]});
  }
}
function nativeDiagram(slide,part){
  clearBody(slide);remove(slide,[...titleNames,...bodyNames]);
  const d=diagrams.diagrams.find(d=>d.id===part.diagram_key);
  if(!d)throw Error(`Unknown diagram ${part.diagram_key}`);
  for(const e of d.edges)route(slide,e.id,e.points,e.dashed,e.arrow_end);
  for(const symbol of d.endpoint_symbols??[]){
    const r=symbol.size_px/2;route(slide,'cross-a',[[symbol.x-r,symbol.y-r],[symbol.x+r,symbol.y+r]],false,false,C.orange);
    route(slide,'cross-b',[[symbol.x-r,symbol.y+r],[symbol.x+r,symbol.y-r]],false,false,C.orange);
  }
  for(const n of d.nodes){
    slide.shapes.add({geometry:'rect',name:`node-${n.id}`,position:{left:n.x,top:n.y,width:n.width,height:n.height},fill:n.focus?'#FFF2E5':C.paper,line:{fill:n.focus?C.orange:'#BECAD5',width:1.2,style:n.dashed?'dash':'solid'}});
    const pad=12,w=n.width-pad*2,title=Array.isArray(n.title)?n.title.join('\n'):n.title;
    const size=n.title_font_px,lines=wrap(title,w,size,true).length,th=lines*size*1.23;
    addText(slide,`node-title-${n.id}`,title,n.x+pad,n.y+9,w,th+5,size,C.navy,true);
    const sub=n.subtitle.join('\n'),sy=n.y+9+th+7;
    addText(slide,`node-sub-${n.id}`,sub,n.x+pad,sy,w,n.y+n.height-sy-5,17,C.muted);
  }
  for(const e of d.edges)if(e.label){
    const b=e.label_box;addText(slide,`label-${e.id}`,Array.isArray(e.label)?e.label.join('\n'):e.label,b.x,b.y,b.width,b.height+6,17,C.muted);
  }
  for(const [i,c]of(d.callouts??[]).entries())addText(slide,`diagram-callout-${i}`,c.text.join('\n'),c.x,c.y,c.width,c.height,c.font_px,C.muted);
  addText(slide,'diagram-principle',d.footer,72,588,1136,23,15,C.muted);
  slide.speakerNotes.textFrame.setText(d.notes.join('\n'));
}
async function sourceImage(slide,part){
  clearBody(slide);remove(slide,[...titleNames,...bodyNames]);
  const file=path.resolve(root,part.image_path);
  let svg=await fs.readFile(file,'utf8');
  const viewBox=svg.match(/viewBox="([^"]+)"/)[1].split(/\s+/).map(Number);
  svg=svg.replace(/<svg\b[^>]*>/,tag=>tag.replace(/\s(?:width|height)="[^"]*"/g,'').replace('<svg',`<svg width="${viewBox[2]*4}" height="${viewBox[3]*4}"`));
  const image=await loadImage(Buffer.from(svg)),canvas=new Canvas(image.width,image.height);
  canvas.getContext('2d').drawImage(image,0,0);
  slide.images.add({blob:new Uint8Array(await canvas.toBuffer('png')),contentType:'image/png',alt:`Исходная схема Claude: ${path.basename(file)}`,fit:'contain',position:{left:72,top:171,width:1136,height:430}});
}
function gates(slide,part){
  clearBody(slide);remove(slide,[...titleNames,...bodyNames]);
  const xs=[72,454,836],w=352;
  for(let i=0;i<2;i++)route(slide,`stage-${i}`,[[xs[i]+w,203],[xs[i+1]-9,203]],false,true,C.orange);
  part.blocks.forEach((b,i)=>{
    addText(slide,`stage-number-${i}`,`0${i+1}`,xs[i],176,w,34,25,C.orange,true);
    addText(slide,`stage-title-${i}`,b.heading,xs[i],216,w,68,24,C.navy,true);
    addText(slide,`stage-body-${i}`,b.body,xs[i],288,w,166,18,C.muted);
    const g=part.gates[i];
    addText(slide,`stage-result-${i}`,`Результат: ${g.result}`,xs[i],464,w,55,18,C.navy,true);
    addText(slide,`stage-gate-${i}`,`Переход: ${g.gate}`,xs[i],522,w,51,17,C.muted);
    addText(slide,`stage-owner-${i}`,g.owner,xs[i],576,w,30,15,C.muted);
  });
}
function cover(slide,part){
  remove(slide,['Oval 5','Oval 6','Oval 7','Rectangle 8','Rounded Rectangle 9','Rectangle 10','Rounded Rectangle 11','Rectangle 12','Rounded Rectangle 13','Rectangle 14']);
  slide.images.add({blob:coverImage,contentType:'image/png',alt:'Принтер этикеток, каталог и консультация в чате. Концептуальная иллюстрация.',prompt:coverPrompt,fit:'contain',crop:{left:0.1,top:0.04,right:0.1,bottom:0.08},position:{left:790,top:108,width:430,height:355}});
  text(slide,'Rectangle 2',part.subtitle.toUpperCase(),142,52,660,28,14,C.orange,true);
  text(slide,'cover-title',part.cover_display_title??part.title,78,128,728,236,54,C.white,true);
  text(slide,'Rectangle 4',part.cover_description??part.blocks.map(b=>b.body).join('\n'),82,397,720,136,22,'#D9E7F3');
  const c=data.contacts.find(c=>c.id===part.contact_id);
  text(slide,'Rectangle 16',`${c.name}\n${c.role}\n${c.unit}\n${c.email}\n${c.phone}\nTelegram: @${c.telegram}`,822,488,386,190,19,'#E7EFF5');
  get(slide,'Rectangle 16').text.get(c.name).bold=true;
  get(slide,'Straight Connector 15').position={left:820,top:474,width:388,height:0};
  text(slide,'Rectangle 17',`${part.meeting_label} · ${part.date}\n${part.status} для обсуждения`,82,628,700,58,15,'#D9E7F3');
}
let slideIndex=0;
await fs.mkdir(preview,{recursive:true});
await fs.mkdir(path.join(workspace,'reading-layout'),{recursive:true});
for(const [i,slide]of p.slides.items.entries()){
  slideIndex=i;const part=data.slides[i];
  if(i===0)cover(slide,part);
  else{
    const section=part.section_number?`${String(part.section_number).padStart(2,'0')} · ${part.section_number===1?'ЗАДАЧА':'РЕШЕНИЕ'}  |  `:'';
    text(slide,'kicker-2',`СИНИМЕКС · ${data.client}  |  ${section}${part.kicker}`,112,24,950,25,14,'#9B4F10',true);
    text(slide,'title-2',part.title,64,57,1086,94,31,C.navy,true);
    text(slide,'Rectangle 6',String(i+1).padStart(2,'0'),1172,30,34,21,14,C.white,true,'center');
    const layout=layoutFor(part);
    if(layout==='contents')contents(slide,part);
    else if(layout==='work-comparison')workComparison(slide,part);
    else if(layout==='context-diptych')await contextDiptych(slide,part);
    else if(layout==='annotated-choice')annotatedChoice(slide,part);
    else if(layout==='catalog-anatomy')catalogAnatomy(slide,part);
    else if(layout==='answer-evidence')answerEvidence(slide,part);
    else if(layout==='options-table')optionsTable(slide,part);
    else if(layout==='value-tree')valueTree(slide,part);
    else if(layout==='acceptance-cases')acceptanceCases(slide,part);
    else if(layout==='executive-summary')executiveSummary(slide,part);
    else if(layout==='section-intro')sectionIntro(slide,part);
    else if(layout==='diagram')nativeDiagram(slide,part);
    else if(layout==='source-image')await sourceImage(slide,part);
    else if(layout==='gates')gates(slide,part);
    else if(layout==='method-table')matrix(slide,part,true);
    else if(layout==='three-column')columns(slide,part);
    else if(layout==='company')columns(slide,part,false,true);
    else if(layout==='timeline')columns(slide,part,true);
    else if(layout==='two-column')comparison(slide,part);
    else if(layout==='scenario')comparison(slide,part,true);
    else if(layout==='matrix')matrix(slide,part);
    else rows(slide,part);
    const takeaway=part.takeaway.charAt(0).toUpperCase()+part.takeaway.slice(1);
    text(slide,'Rectangle 29',takeaway,88,620,1100,43,18,C.navy,true);
    const s=slide.shapes.add({geometry:'textbox',name:'source-rail',position:{left:72,top:690,width:1136,height:18},fill:'none',line:{fill:'none',width:0}});
    const publicSources=part.sources.filter(s=>s.url).map(s=>new URL(s.url).hostname).filter((s,i,a)=>a.indexOf(s)===i).join(' · ');
    s.text=part.source_label??(publicSources?`Источники: ${publicSources} · ${data.date}`:`Рабочая концепция к первой встрече · ${data.date}`);
    s.text.style={fontSize:12.5,typeface:'Calibri',color:C.muted,insets:{left:0,right:0,top:0,bottom:0},verticalAlignment:'top'};
  }
  slide.speakerNotes.textFrame.setText([part.title,...part.blocks.map(b=>`${b.heading}\n${b.body}`),...(part.visual_copy?[JSON.stringify(part.visual_copy,null,2)]:[]),part.takeaway,part.notes,...(part.diagram_key?diagrams.diagrams.find(d=>d.id===part.diagram_key).notes:[]),'Источники:',JSON.stringify(part.sources,null,2),
    ...(part.company_facts??[]).map(id=>JSON.stringify(data.company.facts.find(f=>f.id===id))),...(part.company_proof??[]).map(id=>JSON.stringify(data.company.proof.find(f=>f.id===id))),
    'Статус: рабочая концепция; состав пилота и требования подлежат согласованию.']);
  const png=await p.export({slide,format:'png',scale:1.5});
  await fs.writeFile(path.join(preview,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
  const layout=await slide.export({format:'layout'});await fs.writeFile(path.join(workspace,'reading-layout',`slide-${i+1}.json`),await layout.text());
}
const pptx=await PresentationFile.exportPptx(p);await pptx.save(out);
const digest=async file=>createHash('sha256').update(await fs.readFile(file)).digest('hex');
const inputFile=path.resolve(args.spec);
const visualAssets=[...new Set(data.slides.filter(s=>s.layout==='context-diptych').flatMap(s=>[path.resolve(root,s.image_path),path.resolve(root,s.image_path.replace(/\.[^.]+$/,'.prompt.json'))]))];
const manifest={document:'presentation',id:data.id??'reading-deck',date:data.date,slides:data.slides.length,style:'cinimex-consulting',output:path.basename(out),sha256:await digest(out),
  deck_version:data.deck_version??2,
  inputs:[inputFile,path.join(root,'src/content/company.yaml'),path.join(root,'templates/presentations/cinimex-consulting/template.json'),coverAsset,path.resolve(args.diagrams),fileURLToPath(import.meta.url),path.join(root,'templates/presentations/cinimex-consulting/style.yaml'),...visualAssets].map(file=>({name:path.basename(file),path:file})),
  workspace,preview,checks:{native_template_clone:true,full_visible_copy:true,visual_review:false,pdf_built:false,powerpoint_opened:false,editorial_review:true}};
for(const input of manifest.inputs)input.sha256=await digest(input.path);
await fs.writeFile(out.replace(/\.pptx$/,'.manifest.json'),JSON.stringify(manifest,null,2));
await fs.writeFile(path.join(workspace,'reading-text-checks.json'),JSON.stringify(checks,null,2));
console.log(JSON.stringify({output:out,preview,slides:p.slides.items.length}));
