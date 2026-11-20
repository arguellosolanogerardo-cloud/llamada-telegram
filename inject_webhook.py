import io

with io.open('bot_comandos.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"' in line:
        lines[i] = '            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"\n'
        break

with io.open('bot_comandos.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
