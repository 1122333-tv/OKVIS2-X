#!/usr/bin/env node
// Render a saved local Markdown report with embedded images. Requires marked.
import {createRequire} from 'node:module';
import {readFileSync, writeFileSync, mkdirSync, existsSync} from 'node:fs';
import {resolve, dirname, extname} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';

const [sourceArg, outputArg] = process.argv.slice(2);
if (!sourceArg || !outputArg) throw Error('Usage: render_vio_drift_markdown.mjs SOURCE.md OUTPUT.html');
const source=resolve(sourceArg), output=resolve(outputArg);
if (existsSync(output) || existsSync(output+'.provenance.json')) throw Error('Output already exists');
const require=createRequire(import.meta.url);
const {marked}=await import(pathToFileURL(require.resolve('marked')).href);
const markdown=readFileSync(source,'utf8');
if (/<!--\s*[A-Z_]+\s*-->/.test(markdown)) throw Error('Report still contains unfinished placeholders');
const hash=buffer=>createHash('sha256').update(buffer).digest('hex');
const images=[];
const body=marked.parse(markdown, {walkTokens(token) {
  if (token.type==='image') {
    if (/^[a-z][a-z0-9+.-]*:/i.test(token.href)) throw Error('Expected a local report image');
    const path=resolve(dirname(source),decodeURIComponent(token.href));
    const mime={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg'}[extname(path).toLowerCase()];
    if (!mime) throw Error('Unsupported report image: '+path);
    const bytes=readFileSync(path);
    images.push({path,sha256:hash(bytes),bytes:bytes.length});
    token.href=`data:${mime};base64,${bytes.toString('base64')}`;
  } else if (token.type==='link' && !/^(?:[a-z][a-z0-9+.-]*:|#)/i.test(token.href)) {
    token.href=pathToFileURL(resolve(dirname(source),decodeURIComponent(token.href))).href;
  }
}});
const html=`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>稳定复现模式 VIO 漂移报告</title><style>
body{font:16px/1.65 system-ui,sans-serif;max-width:1200px;margin:32px auto;padding:0 24px;color:#18212b}h1,h2{line-height:1.3}h2{margin-top:2em}img{max-width:100%;height:auto}table{border-collapse:collapse;font-size:14px;display:block;overflow-x:auto}td,th{padding:7px 10px;border:1px solid #cbd2da;text-align:left}th{background:#edf2f7}pre{overflow-x:auto;padding:16px;background:#f3f5f7}code{font-family:monospace;overflow-wrap:anywhere}a{color:#1458a5}blockquote{border-left:4px solid #aaa;margin-left:0;padding-left:18px}
</style><body>${body}</body></html>`;
mkdirSync(dirname(output),{recursive:true});
writeFileSync(output,html,{flag:'wx'});
writeFileSync(output+'.provenance.json',JSON.stringify({source,source_sha256:hash(markdown),html_sha256:hash(html),images},null,2),{flag:'wx'});
console.log(JSON.stringify({output,embedded_images:images.length}));
