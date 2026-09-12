import assert from 'node:assert/strict';
import {compositionVariants,pointNumber} from '../scripts/ppt_layouts.mjs';
const page=(layout,enabled=true)=>({layout,enabled});
assert.deepEqual(compositionVariants([page('conclusions'),page('conclusions'),page('conclusions')]),[0,1,0]);
assert.deepEqual(compositionVariants([page('comparison'),page('risk'),page('comparison')]),[0,1,0]);
assert.deepEqual(compositionVariants([page('chart'),page('flow',false),page('chart')]),[0,1]);
assert.deepEqual(compositionVariants([page('flow'),page('chart'),page('flow')]),[0,0,0]);
assert.deepEqual([0,1,2,3].map(pointNumber),['01','02','03','04']);
console.log('PPT composition and numbering tests passed');
