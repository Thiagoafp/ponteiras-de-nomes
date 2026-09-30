#!/bin/bash
# Baixa fontes livres (licença OFL / Apache) do repositório oficial github.com/google/fonts para a pasta fontes/.
# Uso: bash baixar_fontes.sh        (já baixadas são puladas)
cd "$(dirname "$0")" && mkdir -p fontes && cd fontes
R="https://raw.githubusercontent.com/google/fonts/main"
LISTA="
ofl/lobster/Lobster-Regular
ofl/lobstertwo/LobsterTwo-Bold
ofl/pacifico/Pacifico-Regular
apache/chewy/Chewy-Regular
apache/luckiestguy/LuckiestGuy-Regular
ofl/modak/Modak-Regular
ofl/titanone/TitanOne-Regular
ofl/mousememoirs/MouseMemoirs-Regular
ofl/sigmarone/SigmarOne-Regular
ofl/bubblegumsans/BubblegumSans-Regular
ofl/pixelifysans/PixelifySans%5Bwght%5D
ofl/silkscreen/Silkscreen-Bold
ofl/pressstart2p/PressStart2P-Regular
ofl/vt323/VT323-Regular
ofl/jersey10/Jersey10-Regular
ofl/tiny5/Tiny5-Regular
ofl/micro5/Micro5-Regular
ofl/pirataone/PirataOne-Regular
ofl/jollylodger/JollyLodger-Regular
ofl/newrocker/NewRocker-Regular
ofl/sancreek/Sancreek-Regular
ofl/rye/Rye-Regular
ofl/ribeye/Ribeye-Regular
ofl/notoemoji/NotoEmoji%5Bwght%5D
ofl/notosanssymbols2/NotoSansSymbols2-Regular
ofl/courgette/Courgette-Regular
ofl/damion/Damion-Regular
ofl/satisfy/Satisfy-Regular
ofl/playball/Playball-Regular
ofl/emilyscandy/EmilysCandy-Regular
ofl/lilyscriptone/LilyScriptOne-Regular
ofl/dancingscript/DancingScript%5Bwght%5D
ofl/sacramento/Sacramento-Regular
ofl/greatvibes/GreatVibes-Regular
"
for f in $LISTA; do
  n=$(basename "$f" | sed 's/%5B.*//')
  if [ -s "$n.ttf" ]; then continue; fi
  code=$(curl -s -L -o "$n.ttf" -w "%{http_code}" "$R/$f.ttf")
  sz=$(stat -c %s "$n.ttf" 2>/dev/null)
  if [ "$code" != "200" ] || [ "${sz:-0}" -lt 5000 ]; then rm -f "$n.ttf"; echo "FALHOU $f ($code)"; else echo "ok $n.ttf $sz"; fi
done
