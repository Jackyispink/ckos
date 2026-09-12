// Re-render an immutable saved export without modifying the report or PPT task.
import fs from 'node:fs/promises';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const input=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
input.runtime=JSON.parse(await fs.readFile(path.join(root,'config/ppt_runtime.json'),'utf8'));
input.output=path.join(root,'storage',`ppt-layout-review-${Date.now()}`);
await fs.mkdir(input.output,{recursive:true});
const file=path.join(input.output,'input.json');
await fs.writeFile(file,JSON.stringify(input));
console.log(input.output);
const result=spawnSync(process.execPath,[path.join(root,'scripts/render_presentation.mjs'),file],{stdio:'inherit'});
process.exitCode=result.status??1;
