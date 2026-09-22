#!/usr/bin/env python3
"""Generate a self-contained Chinese report from a version-2 OKVIS run."""
import argparse
import base64
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import shutil
import tempfile
import yaml
from pipeline_layout import read_manifest, artifact, sha, dump


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
    data={'run':str(run),'run_status':m['status'],'stages':m['stages'],'parameters':m['parameters'],'vio':vio,
          'comparison':comp,'reference':ref,'groundtruth':gt,'time_offset':offset,'configuration_changes':changes,'missing':missing,
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
        relative=str(p.relative_to(run));sources[relative]=sha(p)
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
    section('overview','输入与运行状态','<p>'+e(run.name)+'</p>'+file_block('运行输入参数、数据引用及各阶段状态。',run/'manifest.yaml',{'parameters':m['parameters'],'stages':m['stages']},'parameters / stages；自动报告生成时显示预期完成状态' if automatic else 'parameters / stages'))
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
    section('masks','Mask','<details><summary>展开 Mask 图像</summary>'+(''.join(figure(p) for p in sorted((run/'01_preparation/outputs/masks').glob('*.png'))) or '<p>暂无 Mask 图像</p>')+'</details>')
    section('diagnostics','对齐诊断',''.join(figure(p) for p in sorted((run/'04_vio_comparison').glob('*.png')))+file_block('对齐方式、评测时间范围、共同时间戳及对齐诊断。',artifact(run,'comparison'),{k:v for k,v in comp.items() if k not in ('native','common')},'除 native / common 外的字段'))
    section('sources','来源与缺失项',file_block('导入参考文件的原始来源路径和 SHA-256。',run/'02_reference/inputs/sources.json',ref)+file_block('生成报告时未找到的输入文件清单；空列表表示未发现缺失。',run/'report/report_data.json',missing,'missing'))
    def safe(v):
        if isinstance(v,int) and not isinstance(v,bool) and abs(v)>2**53-1:return str(v)
        if isinstance(v,dict):return {k:safe(x) for k,x in v.items()}
        if isinstance(v,list):return [safe(x) for x in v]
        return v
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OKVIS VIO 评测报告</title>
<style>body{max-width:1200px;margin:32px auto;padding:0 24px;font:16px/1.65 system-ui;color:#202b36;background:#fafbfc}nav{display:flex;gap:18px;flex-wrap:wrap}a{color:#155c9c}section{margin:30px 0;padding:22px;background:white;border:1px solid #dbe2e8;border-radius:10px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #dbe2e8;padding:8px;text-align:left;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;max-height:420px;overflow:auto}img{max-width:100%}.zoom{background:none;border:0;cursor:zoom-in;width:100%}figure{margin:20px 0}figcaption{font-size:12px;overflow-wrap:anywhere}.file-path{overflow-wrap:anywhere;font-size:13px}.file-block{margin:18px 0}dialog{max-width:95vw;max-height:95vh;padding:12px}dialog img{max-height:85vh}button{padding:8px} @media print{nav,input,dialog{display:none}pre{max-height:none;overflow:visible}section{break-inside:auto}figure{break-inside:avoid}}</style>
<style>.table-scroll{overflow-x:auto}.metrics{white-space:nowrap}.metrics td,.metrics th{overflow-wrap:normal}.plots{table-layout:fixed;min-width:760px}.plots td{vertical-align:top}.plots figure{margin:0}.plots .zoom{padding:0}summary{cursor:pointer;font-weight:600}details{margin:14px 0}body{max-width:1560px}</style>
<h1>OKVIS VIO 评测报告</h1>'''
    page+='<nav>'+''.join('<a href="#'+id+'">'+e(title)+'</a>' for id,title,_ in sections)+'</nav>'+''.join(body for _,_,body in sections)
    page+='''<dialog id="viewer"><button id="close">关闭</button><img id="large" alt="放大的评测图"></dialog><script>
const viewer=document.getElementById('viewer');document.querySelectorAll('.zoom').forEach(b=>b.onclick=()=>{document.getElementById('large').src=b.querySelector('img').src;viewer.showModal()});document.getElementById('close').onclick=()=>viewer.close();window.addEventListener('beforeprint',()=>document.querySelectorAll('details').forEach(d=>d.open=true));
</script></html>'''
    target=run/'report';target.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target,prefix='.generate-') as tmp:
        tmp=Path(tmp)
        (tmp/'index.html').write_text(page)
        dump(tmp/'report_data.json',safe(data))
        dump(tmp/'generation.json',{'status':'complete','generated_utc':datetime.now(timezone.utc).isoformat(),'sources_sha256':sources,'missing':missing,'embedded_pngs':len(images)})
        for name in ('index.html','report_data.json','generation.json'):(tmp/name).replace(target/name)
    (target/'logs').mkdir(exist_ok=True)
    (target/'logs/stage.log').write_text('Report generated from existing artifacts; estimator/evo not invoked.\n')
    return target/'index.html'

if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--run',required=True,type=Path);a=p.parse_args();print(generate(a.run))
