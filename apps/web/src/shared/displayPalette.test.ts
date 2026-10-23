import { expect, it } from "vitest";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import path from "node:path";

it("keeps every authored CSS/Canvas/SVG color outside green hues, including pale green neutrals", () => {
  const root=path.resolve(existsSync("apps/web/src") ? "apps/web/src" : "src");
  const files=(dir:string):string[]=>readdirSync(dir,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?files(path.join(dir,entry.name)):[path.join(dir,entry.name)]);
  const green:string[]=[];
  for(const file of files(root).filter(f=>/\.(css|tsx|ts)$/.test(f)&&!f.includes(".test.")&&!f.includes("generated"))){
    const source=readFileSync(file,"utf8");
    for(const match of source.matchAll(/#([\da-f]{6})(?:[\da-f]{2})?\b|rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/gi)){
      const rgb=match[1]?[0,2,4].map(i=>parseInt(match[1]!.slice(i,i+2),16)):[Number(match[2]),Number(match[3]),Number(match[4])];
      const [r,g,b]=rgb.map(n=>n/255) as [number,number,number];const max=Math.max(r,g,b),min=Math.min(r,g,b),d=max-min;
      if(d===0)continue;let h=(max===r?(g-b)/d+(g<b?6:0):max===g?(b-r)/d+2:(r-g)/d+4)*60;
      if(h>=75&&h<=175)green.push(`${file.slice(root.length+1)}:${match[0]}`);
    }
  }
  expect(green).toEqual([]);
});
