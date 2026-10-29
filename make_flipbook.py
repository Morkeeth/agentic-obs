from pathlib import Path
import subprocess,json,datetime
p=Path(__file__).resolve().parent
frames=[('01-science-desk.png','Local prototype: built-in looks. No model connected.'),('02-weather-ready.png','Weather draft: camera right. 9-second countdown.'),('03-weather-revised.png','Revision: camera left. Quiet motion. Reveal hold: 8 seconds.'),('04-weather-rehearsal.png','Rehearse: countdown plays. Program remains unchanged.'),('05-weather-reveal.png','The payoff appears after the countdown.'),('06-program-taken.png','Take locally: program changes. Nothing sent to OBS or Twitch.'),('07-program-restored.png','Restore: the previous local program returns.'),('08-space-desk.png','Second example: coffee mission control. Save and reuse it.')]
concat=p/'screens.concat';concat.write_text(''.join("file '"+str(p/name)+"'\nduration 3\n" for name,label in frames)+"file '"+str(p/frames[-1][0])+"'\n")
filters=['scale=1280:-2','pad=1280:720:0:0:color=0x14241d']
for i,(name,label) in enumerate(frames):
 text=p/f'caption-{i}.txt';text.write_text('ACTUAL UI STEP CAPTURES  /  '+label)
 # filters.append(f"drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:textfile='{text}':fontcolor=white:fontsize=21:x=24:y=663:enable='gte(t,{i*3})*lt(t,{(i+1)*3})'")
cmd=['ffmpeg','-y','-v','error','-threads','2','-f','concat','-safe','0','-i',str(concat),'-vf',','.join(filters),'-an','-c:v','libx264','-threads','2','-filter_threads','2','-preset','fast','-crf','21','-r','12','-pix_fmt','yuv420p','-t','24','-movflags','+faststart',str(p/'AGENTIC-OBS-ACTUAL-UI-STEP-FLIPBOOK.mp4')]
subprocess.run(cmd,check=True)
subprocess.run(['ffmpeg','-y','-v','error','-threads','2','-i',str(p/'AGENTIC-OBS-ACTUAL-UI-STEP-FLIPBOOK.mp4'),'-vf','fps=1,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse','-filter_complex_threads','2','-filter_threads','2','-loop','0',str(p/'AGENTIC-OBS-STEP-FLIPBOOK.gif')],check=True)
print(json.dumps({'status':'encoded','at':datetime.datetime.now().astimezone().isoformat(),'frames':[x[0] for x in frames],'type':'Actual UI screenshot step flipbook; not continuous recording','seconds':24}))
