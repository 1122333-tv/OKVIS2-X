#!/usr/bin/env python3
"""Create an offline six-sequence OKVIS/Basalt report from saved evaluations."""
import argparse
import base64
import csv
import html
import io
import json
from pathlib import Path
import shutil
import numpy as np
import yaml
from PIL import Image
from pipeline_layout import dump,sha,artifact_hashes
from run_poc_batch import SCENES

TITLES={'static_H_30s':'水平静止','static_V_30s':'竖直静止','small_move':'小范围运动',
        'big_move':'大范围运动','dynamic_background':'动态背景','static_H_30s_humanmove':'水平静止／有人经过（补充）'}


def bias_plot(run,output,origin):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    p=run/'03_vio/outputs/okvis2-vio_trajectory.csv'
    with p.open() as f:
        reader=csv.DictReader(f);rows=[{k.strip():v.strip() for k,v in r.items() if k} for r in reader]
    ts=np.array([int(r['timestamp']) for r in rows],dtype=np.int64)
    bias=np.array([[float(r['b_'+kind+'_'+axis]) for axis in 'xyz' for kind in ('g','a')] for r in rows])
    t=(ts-origin)/1e9;cuts=np.flatnonzero(np.diff(ts)>1.8*np.median(np.diff(ts)))+1
    fig,axes=plt.subplots(2,1,figsize=(10,5),sharex=True,layout='constrained')
    for i,(ax,kind,unit) in enumerate(zip(axes,['g','a'],['rad/s','m/s²'])):
        for j,axis in enumerate('xyz'):
            ax.plot(np.insert(t,cuts,np.nan),np.insert(bias[:,j*2+i],cuts,np.nan),
                    color=['#0072B2','#D55E00','#009E73'][j],ls=['-','--',':'][j],label=axis.upper())
        ax.set(ylabel='Bias '+kind+' ('+unit+')');ax.grid(alpha=.2);ax.legend(ncol=3)
    axes[-1].set_xlabel('Time since first input group (s)');fig.savefig(output,dpi=150);plt.close(fig)
    return dict(first={k:[float(rows[0]['b_'+k+'_'+x]) for x in 'xyz'] for k in ('g','a')},
                last={k:[float(rows[-1]['b_'+k+'_'+x]) for x in 'xyz'] for k in ('g','a')},
                note='OKVIS estimated total bias from raw IMU; not directly comparable with Basalt residual bias')


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('experiment',type=Path);a=p.parse_args()
    root=a.experiment.resolve();state=json.loads((root/'state.json').read_text())
    out=root/'report';out.mkdir(exist_ok=True);assets=out/'assets';assets.mkdir(exist_ok=True)
    baseline=json.loads((Path(state['basalt_experiment'])/'summary.json').read_text())
    result=dict(title='1026 POC · OKVIS2 / Basalt VIO',status=state['status'],policy=state['policy'],
                quality_status='NOT_GATED',repeats=1,sequences={},sources={})
    for f in [root/'state.json',root/'preservation.json',root/'validation/basalt_equivalence.json',root/'validation/tests.log',
              root/'validation/tests_after_recovery.log',root/'validation/execution_recovery.json',Path(__file__)]:
        if f.is_file():result['sources'][str(f)]=sha(f)
    metrics=[];sections=[];overview=[];image_records=[]
    e=lambda v:html.escape(str(v),quote=True)
    def table(head,rows):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+e(x)+'</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+e(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    def fig(path,caption):
        with Image.open(path) as im:im.verify()
        payload=path.read_bytes();image_records.append({'path':str(path),'sha256':sha(path),'bytes':len(payload)})
        return '<figure><button class="zoom"><img loading="lazy" alt="'+e(caption)+'" src="data:image/png;base64,'+base64.b64encode(payload).decode()+'"></button><figcaption>'+e(caption)+'</figcaption></figure>'
    def number(v):return '—' if v is None else f'{v:.3f}'
    for scene in SCENES:
        r=state['runs'].get(scene,{})
        if r.get('status')!='complete':
            sections.append('<section id="'+scene+'"><h2>'+e(TITLES[scene])+'</h2><p>运行未完成：'+e(r.get('status','missing'))+'</p></section>');continue
        run=Path(r['run']);comp_path=run/'04_vio_comparison/summary/summary.json';vpath=run/'03_vio/outputs/trajectory_summary.json'
        comp=json.loads(comp_path.read_text());vio=json.loads(vpath.read_text());manifest=yaml.safe_load((run/'manifest.yaml').read_text())
        if manifest['status']!='complete' or manifest['binary']['sha256']!=state['binary_sha256']:
            raise ValueError('Incomplete run or inconsistent executable: '+scene)
        for stage,stage_record in manifest['stages'].items():
            if stage_record['status'] not in ('complete','reused') or artifact_hashes(run/stage_record['directory'])!=stage_record['artifact_sha256']:
                raise ValueError('Saved stage artifacts changed: '+scene+'/'+stage)
        config=yaml.safe_load((run/'03_vio/inputs/okvis2.yaml').read_text().replace('%YAML:1.0',''))
        if config['imu_parameters']['a0']!=[0,0,0] or config['imu_parameters']['g0']!=[0,0,0] or not manifest['sampling']['deterministic'] or vio['show_gui']:
            raise ValueError('Run differs from the requested batch policy: '+scene)
        for f in [comp_path,vpath,run/'manifest.yaml',run/'03_vio/inputs/okvis2.yaml']:
            result['sources'][str(f)]=sha(f)
        if comp.get('common_pairs_verified') is not True:raise ValueError('Common pairs not verified: '+scene)
        records=comp['common'];rows=[]
        for metric,ok in records['okvis']['metric_records'].items():
            ba=records['basalt']['metric_records'][metric]
            if ok['pairs_sha256']!=ba['pairs_sha256']:raise ValueError('Different common pairs')
            factor=100 if ok['unit']=='m' else 1;unit='cm' if factor==100 else '°'
            values=[]
            for name,v in [('okvis',ok),('basalt',ba)]:
                st=v['stats'];values += [number(st[k]*factor) if st else '—' for k in ('rmse','p95')]
                metrics.append(dict(scene=scene,profile=comp['profile'],algorithm=name,metric=metric,
                    status=v['status'],unit=unit,n=st['n'] if st else 0,
                    rmse=st['rmse']*factor if st else None,p95=st['p95']*factor if st else None,
                    pairs_sha256=v['pairs_sha256']))
            rows.append([metric,unit,*values,ok['stats']['n'] if ok['stats'] else 0])
        source=baseline['datasets'][scene]['source']
        record=dict(run=str(run),basalt_run=r['basalt_run'],profile=comp['profile'],vio=vio,
            stage_artifact_hashes_verified=True,
            common_timestamps=comp['common_timestamps'],comparison=comp,
            capture_qa=source.get('capture_status'),capture_errors=source.get('capture_errors'),
            mocap_missing_fraction=source.get('mocap_capture',{}).get('missing_fraction'),
            binary_sha256=manifest['binary']['sha256'],config_sha256=manifest['effective_config_sha256'])
        biasfile=assets/(scene+'_bias.png');record['bias']=bias_plot(run,biasfile,comp['origin_ns'])
        result['sequences'][scene]=record
        def rmse(name,key,factor=1):return records[name]['metrics'].get(key,{}).get('rmse',float('nan'))*factor
        overview.append([TITLES[scene],vio['poses'],vio['missing_groups'],comp['common_timestamps']['n'],
            number(rmse('okvis','ape_translation',100)),number(rmse('basalt','ape_translation',100)),
            number(rmse('okvis','are_rotation')),number(rmse('basalt','are_rotation')),
            number(vio['wall_seconds']),number(vio['wall_realtime_factor']),number(vio['peak_rss_kb']/1024)])
        body='<section id="'+scene+'"><h2>'+e(TITLES[scene])+'</h2>'
        body+='<p>'+('起始 1 s 平均位姿对齐' if comp['profile']=='static' else '整段匹配位置 SE(3) 对齐')+'；无尺度拟合。共同有效位姿 '+str(comp['common_timestamps']['n'])+'。采集 QA：'+e(record['capture_qa'])+'。</p>'
        body+=table(['指标','单位','OKVIS RMSE','OKVIS P95','Basalt RMSE','Basalt P95','共同样本/帧对'],rows)
        if comp['profile']=='static':
            stability=[]
            for name,label in [('okvis','OKVIS'),('basalt','Basalt')]:
                v=records[name]['static_stability']
                stability.append([label,number(v['position_jitter_about_whole_run_mean_m']['rmse']*100),
                    number(v['rotation_jitter_about_whole_run_mean_deg']['rmse']),
                    number(v['end_minus_start_mean_position_m']*100),number(v['end_minus_start_mean_rotation_deg'])])
            body+='<details><summary>静止自身稳定性（共同帧）</summary><p>相对自身整段均值的抖动及首尾 1 s 均值差；不替代与 GT 的误差。</p>'
            body+=table(['算法','位置抖动 RMSE cm','姿态抖动 RMSE °','首尾均值位置差 cm','首尾均值姿态差 °'],stability)+'</details>'
        body+='<p><a href="'+e((run/'report/index.html').as_uri())+'">本机详细报告</a> · 运行目录：<code>'+e(run)+'</code></p>'
        # Common overlay charts share axes and preserve continuity gaps.
        for source_image in sorted((run/'04_vio_comparison').glob('common_*.png')):
            target=assets/(scene+'_'+source_image.name);shutil.copyfile(source_image,target)
            body+=fig(target,TITLES[scene]+' · '+source_image.stem.removeprefix('common_'))
        body+=fig(biasfile,TITLES[scene]+' · OKVIS 在线总 bias（未预扣固定标定）')
        body+='</section>';sections.append(body)
    dump(out/'report_data.json',result)
    if metrics:
        with (out/'metrics.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(metrics[0]));w.writeheader();w.writerows(metrics)
    description='原始 IMU；零初始 bias、在线估计；并行检测 / 匹配 4 线程 / 求解 3 线程；视觉恢复与 IMU Huber=5；固定 RANSAC 种子 12345；关闭 GUI、回环和 final BA。'
    limits='每包一次运行，未验证重复性。固定采样不保证并行轨迹逐位一致。Basalt 参考应用固定 IMU 标定后估计剩余 bias，与本次 OKVIS 的处理不同。GT 使用各包保存结果，不重新拟合时间；共同帧对避开 GT 空洞及已知连续性边界。采集 mocap QA 仍为 REJECT，整体 NOT_GATED。耗时为 VIO 进程墙钟时间，包含数据读取与日志；NAS 缓存和主机负载未控制，不据此判定实时性能。'
    css='body{font:16px/1.6 system-ui,sans-serif;color:#18212b;background:#f2f5f8;margin:0}header,main{max-width:1250px;margin:auto;padding:28px}header{background:#12324b;color:white}h1{font-size:30px}h2{margin-top:0}section{background:white;border-radius:12px;padding:24px;margin:24px 0}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:9px;border-bottom:1px solid #d8e0e8;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}thead{background:#eaf0f6}img{width:100%;height:auto}button.zoom{background:white;border:0;padding:0;width:100%;cursor:zoom-in}figure{margin:20px 0}figcaption{font-size:13px;color:#485464}code{overflow-wrap:anywhere}.notice{border-left:4px solid #b66a00;padding:12px;background:#fff6e7}nav a{margin-right:14px}dialog{max-width:95vw;max-height:95vh}dialog img{max-height:85vh;object-fit:contain}.muted{color:#536170}a{color:#006a9d}'
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+e(result['title'])+'</title><style>'+css+'</style></head><body><header><h1>'+e(result['title'])+'</h1><p>2026-10-28 · 六包单次离线对比 · calibration_1023_B</p><p>'+e(description)+'</p></header><main>'
    page+='<section><h2>共同有效帧上的结果</h2><p>批次状态：'+e(state['status'])+'；已完成 '+str(len(result['sequences']))+' / 6 包。</p><p class="notice">'+e(limits)+'</p>'
    page+=table(['场景','OKVIS位姿','缺失组','共同GT帧','OKVIS APE cm','Basalt APE cm','OKVIS ARE °','Basalt ARE °','OKVIS耗时 s','耗时/序列时长','峰值内存 MiB'],overview)
    page+='<p>静止与运动对齐方式不同，不跨场景排名。平移指标表使用 cm，旋转使用 °。P95 为相关样本的描述统计，不是置信区间。最后一包是原五包报告之外的补充。</p><nav>'+''.join('<a href="#'+s+'">'+e(TITLES[s])+'</a>' for s in SCENES)+'</nav></section>'+''.join(sections)
    page+='<section><h2>验证与数据</h2><p>新评测器在原六包 Basalt 轨迹上逐项复算，统计与原 POC 保存值一致至数值舍入量级。共同 GT 与指标帧对哈希逐项一致。完整精度见同目录 metrics.csv 和 report_data.json；图片已内嵌，可离线查看。</p></section></main><dialog id="viewer"><button id="close">关闭</button><img id="large" alt="放大图表"></dialog><script>const v=document.getElementById("viewer");document.querySelectorAll(".zoom").forEach(b=>b.onclick=()=>{document.getElementById("large").src=b.querySelector("img").src;v.showModal()});document.getElementById("close").onclick=()=>v.close();</script></body></html>'
    (out/'index.html').write_text(page)
    dump(out/'validation.json',dict(sequences=len(result['sequences']),metric_rows=len(metrics),embedded_pngs=len(image_records),images=image_records,
         common_pairs_verified=bool(result['sequences']),verification_scope='Completed sequences included in this report',
         batch_complete=state['status']=='complete' and len(result['sequences'])==6,
         html_sha256=sha(out/'index.html'),report_data_sha256=sha(out/'report_data.json')))
    lines=['# 1026 POC OKVIS2 / Basalt VIO 对比','',
        f"批次状态：{state['status']}；已完成 {len(result['sequences'])} / 6 包。",'',description,'',limits,'',
        '| 场景 | OKVIS APE cm | Basalt APE cm | OKVIS ARE ° | Basalt ARE ° | 共同帧 |',
        '|---|---:|---:|---:|---:|---:|']
    for row in overview:lines.append('| '+' | '.join(map(str,[row[0],row[4],row[5],row[6],row[7],row[3]]))+' |')
    lines+=['','[完整离线报告](report/index.html)','']
    (root/'report.md').write_text('\n'.join(lines))
    print(out/'index.html')


if __name__=='__main__':main()
