import subprocess
from PIL import Image

dur_seg = 60
time_filter = "drawtext=text='%{eif\\:floor(t/60)\\:d\\:2}\\:%{eif\\:floor(mod(t,60))\\:d\\:2}':x=208:y=587:fontcolor=white:fontsize=26"

cmd = [
    'ffmpeg', '-y',
    '-f', 'lavfi', '-i', 'color=c=black:s=1280x720:d=60',
    '-loop', '1', '-i', 'test_bg_bar.png',
    '-loop', '1', '-i', 'test_cover.png',
    '-loop', '1', '-i', 'test_dot.png',
    '-filter_complex', (
        '[0:v][1:v]overlay=0:0[s1]; '
        f'[s1][2:v]overlay=x=\'180 + min(920, 920*t/{dur_seg})\':y=550[s2]; '
        f'[s2][3:v]overlay=x=\'180 + min(920, 920*t/{dur_seg}) - 14\':y=543[s3]; '
        f'[s3]{time_filter}[out]'
    ),
    '-map', '[out]',
    '-ss', '45', '-vframes', '1', 'test_full_45s.png'
]
subprocess.run(cmd, check=True)
im = Image.open('test_full_45s.png')
crop = im.crop((160, 530, 1120, 640))
crop.save('test_bottom_45s.png')
print('45s crop saved!')
