#!/usr/bin/env python3
"""Generate a self-contained Chinese report from a version-2 OKVIS run."""
import argparse
import base64
from datetime import datetime, timezone
import html
import json
import io
from pathlib import Path
import shutil
import tempfile
import yaml
import numpy as np
from PIL import Image
from pipeline_layout import read_manifest, artifact, sha, dump


# Styling follows the Basalt pipeline report; kept local for standalone generation.
CSS = """
:root{color-scheme:light;--ink:#172b3a;--muted:#526977;--line:#d8e2e8;--accent:#006a72}
*{box-sizing:border-box}body{margin:0;background:#f2f5f7;color:var(--ink);font:15px/1.65 system-ui,"Noto Sans CJK SC",sans-serif}
header{background:#153c4b;color:white;padding:38px max(30px,calc((100vw - 1400px)/2));overflow-wrap:anywhere}
.eyebrow{font-size:12px;letter-spacing:.18em;color:#aedfe0}h1{font-size:32px;margin:10px 0}h2{font-size:23px;margin:0 0 20px}h3{margin-top:25px}
.cards{display:flex;gap:15px;flex-wrap:wrap;margin-top:24px}.cards>div{background:#245061;padding:14px 24px;min-width:170px;border-radius:8px}.cards small,.cards strong{display:block}.cards strong{font-size:28px}
.layout{max-width:1450px;margin:auto;display:grid;grid-template-columns:210px minmax(0,1fr);gap:28px;padding:28px}
nav{position:sticky;top:20px;align-self:start}nav a{display:block;padding:9px 12px;border-radius:5px}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
section{background:white;border:1px solid var(--line);border-radius:10px;padding:28px;margin-bottom:22px;scroll-margin-top:20px;overflow-wrap:anywhere}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;max-width:520px;overflow-wrap:anywhere}
th{background:#eaf2f4;font-weight:650}tr:hover td{background:#f7fafb}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f6f7;padding:14px;font-size:12px}
details{margin:14px 0}summary{cursor:pointer;color:var(--accent);font-weight:600}input{padding:9px;border:1px solid #8aadb8;border-radius:5px;font:inherit;width:min(450px,100%)}
.note{background:#fff6df;padding:12px 16px;border-left:3px solid #c18a21}.gallery{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
figure{margin:10px 0;border:1px solid var(--line);padding:10px;border-radius:6px}figure img{width:100%;height:auto}figcaption{font-size:12px;color:var(--muted);overflow-wrap:anywhere}
button{cursor:pointer;border:1px solid var(--line);border-radius:5px;padding:8px 12px;background:white;color:var(--accent)}button.zoom{padding:0;border:0;width:100%}
.masks{display:flex;gap:12px;flex-wrap:wrap}.masks figure{width:170px}dialog{max-width:96vw;max-height:96vh;padding:12px;border:0;border-radius:8px}dialog img{display:block;max-width:90vw;max-height:85vh;object-fit:contain}dialog::backdrop{background:#102530bb}
@media(max-width:850px){.layout{display:block;padding:12px}nav{position:static;display:flex;flex-wrap:wrap;margin-bottom:16px}section{padding:18px}.gallery{grid-template-columns:1fr}}
@media print{body{background:white;font-size:10pt}header{background:white;color:black;padding:0}.cards>div{background:#eef4f5}nav,button,#config-search{display:none!important}button.zoom{display:block!important}.layout{display:block;padding:0}section{border:0;border-radius:0;padding:12px 0;break-before:auto}figure,tr{break-inside:avoid}.gallery{display:block}.scroll{overflow:visible}table{font-size:8pt}a{color:black}dialog{display:none}}

main{min-width:0}.table-scroll{overflow-x:auto}.metrics{white-space:nowrap}.metrics td,.metrics th{overflow-wrap:normal}
.plots{table-layout:fixed;min-width:760px}.plots figure{margin:0}.plots th:first-child{width:14%}
.file-path{font-size:12px;color:var(--muted)}.file-block{margin:18px 0}pre{max-height:420px;overflow:auto}
.mask-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;min-width:760px}.mask-grid figure{margin:8px 0;padding:6px}.mask-grid p{font-size:12px}
button.zoom{cursor:zoom-in}.cards strong{overflow-wrap:anywhere}nav a:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
@media print{pre{max-height:none;overflow:visible}.table-scroll{overflow:visible}.plots,.mask-grid{min-width:0}.metrics{white-space:normal}.mask-grid{gap:6px}.cards strong{font-size:18pt}.eyebrow{color:var(--muted)}}
"""

def differences(a,b,prefix=''):
    if isinstance(a,dict) and isinstance(b,dict):
        out=[]
        for k in sorted(a.keys()|b.keys()):
            key=f'{prefix}.{k}' if prefix else k
            if k not in a:out.append([key,'新增',None,b[k]])
            elif k not in b:out.append([key,'缺失',a[k],None])
            else:out+=differences(a[k],b[k],key)
        return out
    return [] if type(a)==type(b) and json.dumps(a,sort_keys=True)==json.dumps(b,sort_keys=True) else [[prefix,'修改',a,b]]


def compare_masks(run, manifest, sources, missing):
    """Compare valid pixels, accounting for opposite Basalt/OKVIS polarity."""
    inputs=run/'01_preparation/inputs'
    baseline=inputs/'basalt_default_masks'
    origin='运行时保存的 Basalt 默认掩膜快照'
    def key(p):
        return str(p.relative_to(run)) if p.is_relative_to(run) else str(p)
    if not baseline.is_dir():
        origin='历史 run 未保存默认掩膜快照；读取 Basalt 源文件当前内容'
        snapshot=inputs/'basalt_manifest.yaml'
        if snapshot.is_file():
            sources[key(snapshot)]=sha(snapshot)
            bm=yaml.safe_load(snapshot.read_text()) or {}
        else:
            bm={}
        root=manifest.get('parameters',{}).get('basalt_run')
        if root and bm.get('camera_masks',{}).get('enabled'):
            baseline=Path(root)/bm['camera_masks'].get('directory','camera_masks')
        else:
            baseline=None
    records=[]
    for i in range(4):
        default=baseline/f'cam{i}.png' if baseline is not None else None
        actual=run/f'01_preparation/outputs/masks/cam{i}.png'
        row=dict(camera=i,default_path=str(default) if default is not None else None,
                 actual_path=str(actual),status='unknown',changed=None)
        for p in (default,actual):
            if p is not None:
                if p.is_file():sources[key(p)]=sha(p)
                else:missing.append(key(p))
        if default is not None and default.is_file() and actual.is_file():
            with Image.open(default) as im:a=np.asarray(im.convert('L'))<=127
            with Image.open(actual) as im:b=np.asarray(im.convert('L'))>127
            row.update(default_valid_pixels=int(a.sum()),actual_valid_pixels=int(b.sum()),
                       default_shape=list(a.shape),actual_shape=list(b.shape))
            if a.shape!=b.shape:
                row.update(status='shape_changed',changed=True)
            else:
                changed=int(np.count_nonzero(a!=b))
                row.update(status='changed' if changed else 'same',changed=bool(changed),
                           changed_pixels=changed,newly_excluded_pixels=int((a & ~b).sum()),
                           newly_enabled_pixels=int((~a & b).sum()))
        records.append(row)
    return dict(origin=origin,changed=any(r['changed'] is True for r in records),
                complete=all(r['status']!='unknown' for r in records),cameras=records)


def mask_overlay(default_path, actual_path):
    """Basalt black/white base; green adds exclusions, red removes them."""
    with Image.open(default_path) as im:baseline=np.asarray(im.convert('L'))<=127
    with Image.open(actual_path) as im:actual=np.asarray(im.convert('L'))>127
    if baseline.shape!=actual.shape:
        raise ValueError('Mask dimensions differ; cannot overlay without resampling')
    rgb=np.repeat(np.where(baseline,0,255).astype('uint8')[...,None],3,axis=2)
    rgb[baseline & ~actual]=[0,255,0]
    rgb[~baseline & actual]=[255,0,0]
    return Image.fromarray(rgb)


def generate(run, automatic=False):
    run=Path(run).resolve();m=read_manifest(run);sources={};missing=[]
    if automatic:
        m['status']='complete'
        m['stages']['report']={**m['stages'].get('report',{}),'status':'complete'}
    def read(p,kind='json'):
        if not p.is_file():missing.append(str(p.relative_to(run)));return None
        sources[str(p.relative_to(run))]=sha(p)
        text=p.read_text()
        if kind=='yaml':return yaml.safe_load('\n'.join(l for l in text.splitlines() if not l.startswith('%YAML:')))
        return json.loads(text)
    comp=read(artifact(run,'comparison')) or {}
    vio=read(artifact(run,'vio_summary')) or {}
    default=read(run/'01_preparation/inputs/default_config.yaml','yaml')
    template=read(run/'01_preparation/inputs/algorithm_template.yaml','yaml')
    effective=read(artifact(run,'config'),'yaml')
    ref=read(run/'02_reference/inputs/sources.json') or {}
    gt=read(run/'02_reference/inputs/groundtruth/conversion.json') or {}
    offset=read(run/'02_reference/inputs/time_alignment/total_offset.json')
    changes={'默认到用户':differences(default,template) if default is not None and template is not None else [],
             '用户到运行':differences(template,effective) if template is not None and effective is not None else []}
    masks=compare_masks(run,m,sources,missing)
    sampling=m.get('sampling',{'deterministic':False,'seed':None,'scope':'visual_ransac_only'})
    data={'sampling':sampling,'run':str(run),'run_status':m['status'],'stages':m['stages'],'parameters':m['parameters'],'vio':vio,
          'comparison':comp,'reference':ref,'groundtruth':gt,'time_offset':offset,'configuration_changes':changes,'mask_comparison':masks,'missing':missing,
          'limits':['GT 原样导入；不再次应用时间偏移或外参。','未校验物理 IMU 坐标系或 marker–IMU 标定一致性。',
                    '已准备数据仍引用 Basalt run，源目录及链接目标需要持续可读。','运行成功不代表精度验收通过。']}
    e=lambda v:html.escape(str(v),quote=True)
    def pretty(v):return '<pre>'+e(json.dumps(v,ensure_ascii=False,indent=2))+'</pre>'
    def file_block(description,path,value,field=None,raw=False):
        location=str(path)
        body=('<pre>'+e(path.read_text())+'</pre>') if raw and path.is_file() else pretty(value)
        if not path.is_file() and path != run/'report/report_data.json':
            body='<p>文件缺失，暂无内容。</p>'
        label='查看完整文件内容' if field is None else '查看内容（'+field+'）'
        return '<div class="file-block"><p>'+e(description)+'</p><p class="file-path">文件：<code>'+e(location)+'</code></p><details><summary>'+e(label)+'</summary>'+body+'</details></div>'
    def table(headers,records,cls=''):

        return '<table class="'+cls+'"><thead><tr>'+''.join('<th>'+e(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+e(v)+'</td>' for v in row)+'</tr>' for row in records)+'</tbody></table>'
    metric_names={'ape_translation':'APE 平移','rpe_translation_0.1m':'RPE 平移 · 0.1 m',
                  'rpe_translation_0.5m':'RPE 平移 · 0.5 m','rpe_translation_1m':'RPE 平移 · 1 m'}
    algorithms={'okvis':'OKVIS2','basalt':'Basalt'}
    def metric_table(scope):
        records=comp.get(scope,{})
        keys=['rmse','mean','median','std','min','max','sse','n','p95','p99']
        extras=sorted({k for r in records.values() for s in r.get('metrics',{}).values() for k in s}-set(keys))
        keys+=extras
        headers=['指标','算法']+[{'n':'样本数','sse':'SSE (m²)'}.get(k,k.upper()+' (m)' if k not in extras else k) for k in keys]
        rows=[]
        names=list(dict.fromkeys(k for r in records.values() for k in (*r.get('metrics',{}),*r.get('unavailable_metrics',{}))))
        for metric in names:
            for name,r in records.items():
                s=r.get('metrics',{}).get(metric,{})
                rows.append([metric_names.get(metric,metric),algorithms.get(name,name)]+[
                    format(s[k],'.6g') if isinstance(s.get(k),float) else s.get(k,'—') for k in keys])
        return '<div class="table-scroll">'+table(headers,rows,'metrics')+'</div>'+file_block('完整精度指标、轨迹匹配统计及不可计算原因。',artifact(run,'comparison'),records,scope)
    images=[]
    def figure(p):
        if not p.is_file():return '<p>暂无图表</p>'
        images.append(p)
        relative=str(p.relative_to(run)) if p.is_relative_to(run) else str(p);sources[relative]=sha(p)
        return '<figure><button class="zoom" type="button"><img alt="'+e(relative)+'" src="data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode()+'"></button><figcaption>'+e(p.name)+'</figcaption></figure>'
    def paired_figures(scope):
        root=run/'04_vio_comparison'/scope
        names=sorted({p.name for name in algorithms for p in (root/name).glob('*.png')})
        if not names:return '<p>暂无图表</p>'
        labels={f'{k}_{suffix}.png':v+' · '+label for k,v in metric_names.items()
                for suffix,label in [('raw','误差曲线'),('map','轨迹误差着色')]}
        labels.update({'trajectory_rpy.png':'姿态 RPY','trajectory_speeds.png':'速度',
                       'trajectory_trajectories.png':'空间轨迹','trajectory_xyz.png':'位置 XYZ'})
        rows=''.join('<tr><th scope="row">'+e(labels.get(n,n))+'</th>'+''.join('<td>'+figure(root/a/n)+'</td>' for a in algorithms)+'</tr>' for n in names)
        return '<p>点击图像放大。各图沿用原始坐标轴范围和色标，请结合数值比较。</p><div class="table-scroll"><table class="plots"><colgroup><col style="width:14%"><col style="width:43%"><col style="width:43%"></colgroup><thead><tr><th>指标 / 图表</th><th>OKVIS2</th><th>Basalt</th></tr></thead><tbody>'+rows+'</tbody></table></div>'
    sections=[]
    def section(id,title,body):sections.append((id,title,'<section id="'+id+'"><h2>'+e(title)+'</h2>'+body+'</section>'))
    section('overview','输入与运行状态','<p>'+e(run.name)+'</p><p>视觉 RANSAC 固定采样：'+('开启（种子 12345）' if sampling['deterministic'] else '关闭')+'；仅控制随机采样，不改变线程配置，不保证轨迹逐位一致。</p>'+file_block('运行输入参数、数据引用及各阶段状态。',run/'manifest.yaml',{'parameters':m['parameters'],'stages':m['stages'],'sampling':m.get('sampling',{'deterministic':False,'seed':None,'scope':'visual_ransac_only'})},'parameters / stages；自动报告生成时显示预期完成状态' if automatic else 'parameters / stages'))
    if m['parameters'].get('imu_bias_policy')=='estimate-from-zero':
        section('imu-policy','IMU bias 处理','<p>OKVIS 使用原始 IMU，未应用交付中的固定 bias，a0/g0 为零，在线估计总偏置。Basalt 参考结果应用原固定标定后在线估计剩余偏置。两者此项输入处理不同；原始标定保留。</p>')
    section('reference','参考轨迹与 GT',''.join('<p>'+e(v)+'</p>' for v in data['limits'])+file_block('导入 GT 的转换记录及有效时间段；仅展示来源记录，不重复变换 GT。',run/'02_reference/inputs/groundtruth/conversion.json',gt)+file_block('导入的时间对齐记录；仅作来源说明。',run/'02_reference/inputs/time_alignment/total_offset.json',offset))
    config_paths=[['默认','工程默认配置的运行快照',run/'01_preparation/inputs/default_config.yaml'],
                  ['用户','用户选择的配置模板快照（未指定 --config 时使用默认模板）',run/'01_preparation/inputs/algorithm_template.yaml'],
                  ['运行','实际交给 OKVIS 的最终配置',artifact(run,'config')]]
    section('config','配置差异',table(['配置','说明','具体路径'],config_paths)+
            ''.join('<h3>'+e(k)+'</h3>'+table(['字段','变化',*(['默认值','用户值'] if k=='默认到用户' else ['用户值','运行值'])],rows,'config') for k,rows in changes.items())+
            file_block('完整运行配置，包含相机标定、mask 路径、时间偏移和算法参数。',artifact(run,'config'),effective,raw=True))
    section('coverage','覆盖率与资源统计',file_block('VIO 输出帧数、缺帧、首尾覆盖、特征统计和运行资源汇总。',artifact(run,'vio_summary'),vio))
    section('metrics','Common · APE / RPE','<p>在双方与 GT 均有效的共同时间戳上评测，各自进行 SE(3) 无尺度对齐。表内数值显示 6 位有效数字；完整精度见下方展开项。不可计算的指标显示 —。</p>'+metric_table('common'))
    section('figures','Common · 图表对比',paired_figures('common'))
    section('native','Native · 各自覆盖范围','<details><summary>展开 Native 指标与图表</summary><p>各算法使用自身与 GT 匹配的有效时间戳。</p>'+metric_table('native')+paired_figures('native')+'</details>')
    mask_status=('实际使用的 Mask 与 Basalt 默认 Mask 不同，已自动展开。' if masks['changed'] else
                 '实际使用的 Mask 与 Basalt 默认 Mask 有效区域一致。' if masks['complete'] else
                 '默认或实际 Mask 缺失，无法完整判断差异；不能视为一致。')
    mask_rows=[]
    for r in masks['cameras']:
        mask_rows.append([f"cam{r['camera']}",{'same':'一致','changed':'有效区域变化','shape_changed':'图像尺寸变化','unknown':'无法判断'}[r['status']],
                          r.get('newly_excluded_pixels','—'),r.get('newly_enabled_pixels','—'),
                          r.get('default_valid_pixels','—'),r.get('actual_valid_pixels','—')])
    mask_body='<p>'+e(mask_status)+'</p><p>'+e(masks['origin'])+'</p>'
    mask_body+=table(['相机','差异','新增排除像素','新增有效像素','默认有效像素','实际有效像素'],mask_rows)
    if masks['changed']:
        mask_body+='<p>两次运行的有效图像区域不同，精度对比并非相同掩膜条件。</p>'
    mask_body+='<details'+(' open' if masks['changed'] else '')+'><summary>查看 Mask 前后叠加图（cam0–cam3）</summary>'
    mask_body+='<p>以 Basalt 默认 Mask 为基准：黑色＝保持有效，白色＝保持剔除；<strong style="color:#008000">绿色＝新增剔除区域</strong>，<strong style="color:#c00000">红色＝减少剔除区域（恢复有效）</strong>。已统一有效区域语义，黑白反转本身不算变化；叠加图逐像素生成，不缩放源数据。</p>'
    overlays={}
    mask_body+='<div class="table-scroll"><div class="mask-grid">'
    for r in masks['cameras']:
        mask_body+='<div><strong>cam'+str(r['camera'])+'</strong>'
        if r['status'] in ('same','changed'):
            filename=f"cam{r['camera']}_overlay.png"
            buffer=io.BytesIO();mask_overlay(r['default_path'],r['actual_path']).save(buffer,format='PNG')
            overlays[filename]=buffer.getvalue()
            r['overlay_path']=str(run/'report/mask_overlays'/filename)
            mask_body+='<figure><button class="zoom" type="button"><img alt="cam'+str(r['camera'])+' Mask 前后叠加图" src="data:image/png;base64,'+base64.b64encode(overlays[filename]).decode()+'"></button><figcaption>'+e(filename)+'</figcaption></figure>'
            mask_body+='<p>新增剔除：'+str(r['newly_excluded_pixels'])+' 像素；减少剔除：'+str(r['newly_enabled_pixels'])+' 像素。</p>'
        else:
            mask_body+='<p>'+('图像尺寸不同，无法逐像素叠加。' if r['status']=='shape_changed' else 'Mask 缺失，无法生成叠加图。')+'</p>'
        mask_body+='<details><summary>源 Mask 路径</summary><p class="file-path">Basalt：'+e(r['default_path'] or '—')+'</p><p class="file-path">OKVIS：'+e(r['actual_path'])+'</p></details></div>'
    mask_body+='</div></div>'
    section('masks','Mask',mask_body+'</details>')
    section('diagnostics','对齐诊断',''.join(figure(p) for p in sorted((run/'04_vio_comparison').glob('*.png')))+file_block('对齐方式、评测时间范围、共同时间戳及对齐诊断。',artifact(run,'comparison'),{k:v for k,v in comp.items() if k not in ('native','common')},'除 native / common 外的字段'))
    section('sources','来源与缺失项',file_block('导入参考文件的原始来源路径和 SHA-256。',run/'02_reference/inputs/sources.json',ref)+file_block('生成报告时未找到的输入文件清单；空列表表示未发现缺失。',run/'report/report_data.json',missing,'missing'))
    def safe(v):
        if isinstance(v,int) and not isinstance(v,bool) and abs(v)>2**53-1:return str(v)
        if isinstance(v,dict):return {k:safe(x) for k,x in v.items()}
        if isinstance(v,list):return [safe(x) for x in v]
        return v
    status_labels={'complete':'已完成','failed':'失败','running':'运行中'}
    cards=[('运行状态',status_labels.get(m['status'],m['status'])),
           ('VIO 位姿',vio.get('poses','—')),
           ('共同时间戳',comp.get('common_timestamps',{}).get('n','—')),
           ('变化掩膜',sum(r['changed'] is True for r in masks['cameras']) if masks['complete'] else '未完整核对')]
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+e(run.name)+' · OKVIS VIO 评测报告</title><style>'+CSS+'</style></head><body>'
    page+='<header><div class="eyebrow">OKVIS2 · OFFLINE PIPELINE</div><h1>视觉惯性管线报告</h1><p>OKVIS2 / Basalt · VIO 评测</p><p>'+e(run.name)+'</p><div class="cards">'+''.join('<div><small>'+e(k)+'</small><strong>'+e(v)+'</strong></div>' for k,v in cards)+'</div></header>'
    page+='<div class="layout"><nav aria-label="报告章节">'+''.join('<a href="#'+id+'">'+e(title)+'</a>' for id,title,_ in sections)+'<button type="button" onclick="window.print()">打印报告</button></nav><main>'+''.join(body for _,_,body in sections)+'</main></div>'
    page+='''<dialog id="viewer" aria-label="图表放大"><button id="close" type="button">关闭</button><img id="large" alt="放大的评测图"></dialog><script>
const viewer=document.getElementById('viewer');document.querySelectorAll('.zoom').forEach(b=>b.onclick=()=>{const source=b.querySelector('img');const large=document.getElementById('large');large.src=source.src;large.alt=source.alt;viewer.showModal()});document.getElementById('close').onclick=()=>viewer.close();
window.addEventListener('beforeprint',()=>document.querySelectorAll('details').forEach(d=>{d.dataset.wasOpen=String(d.open);d.open=true}));
window.addEventListener('afterprint',()=>document.querySelectorAll('details').forEach(d=>d.open=d.dataset.wasOpen==='true'));
</script></body></html>'''
    target=run/'report';target.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target,prefix='.generate-') as tmp:
        tmp=Path(tmp)
        (tmp/'index.html').write_text(page)
        overlay_dir=target/'mask_overlays';overlay_dir.mkdir(exist_ok=True)
        for name,content in overlays.items():
            (tmp/name).write_bytes(content)
            (tmp/name).replace(overlay_dir/name)
        for old in overlay_dir.glob('cam*_overlay.png'):
            if old.name not in overlays:old.unlink()
        dump(tmp/'report_data.json',safe(data))
        dump(tmp/'generation.json',{'status':'complete','generated_utc':datetime.now(timezone.utc).isoformat(),'sources_sha256':sources,'missing':missing,'embedded_pngs':len(images)+len(overlays),
                                   'mask_overlays_sha256':{name:sha(overlay_dir/name) for name in overlays}})
        for name in ('index.html','report_data.json','generation.json'):(tmp/name).replace(target/name)
    (target/'logs').mkdir(exist_ok=True)
    (target/'logs/stage.log').write_text('Report generated from existing artifacts; estimator/evo not invoked.\n')
    return target/'index.html'

if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--run',required=True,type=Path);a=p.parse_args();print(generate(a.run))
