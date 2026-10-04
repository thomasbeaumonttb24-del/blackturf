# Génère les boutons « avis » des e-mails : frontend/public/img/email/avis-*.png
#
# Les mails n'exécutent pas le widget Trustpilot et n'affichent pas de SVG : les
# boutons y sont des images, dessinées à partir des logos OFFICIELS rangés dans
# frontend/public/img/logos/ (trustpilot.svg = logo de cdn.trustpilot.net/brand-assets,
# google-g.svg = « G » de Google). Une image garde ses couleurs en mode sombre, là
# où un bouton HTML se fait inverser par Gmail.
#
# Relancer après une modification des logos (Windows, Edge installé) :
#   powershell -ExecutionPolicy Bypass -File scripts\generer_boutons_avis.ps1
$racine = Split-Path $PSScriptRoot -Parent
$logos = ($racine + "\frontend\public\img\logos").Replace('\', '/')
$tmp = Join-Path $env:TEMP "bt-boutons-avis"
New-Item -ItemType Directory -Force $tmp | Out-Null
$boutons = @(
  @{ nom = "avis-trustpilot"; l = 272; html = "<div class=`"b`" style=`"border:1.5px solid #00B67A`">&Eacute;valuez-nous sur<img src=`"file:///$logos/trustpilot.svg`" style=`"height:22px;margin-top:-3px`"></div>" },
  @{ nom = "avis-google"; l = 252; html = "<div class=`"b`" style=`"border:1.5px solid #DADCE0`"><img src=`"file:///$logos/google-g.svg`" style=`"height:22px`">Laisser un avis <b>Google</b></div>" }
)
foreach ($b in $boutons) {
  $page = "<!doctype html><meta charset=`"utf-8`"><style>html,body{margin:0;background:transparent;font-family:Arial,Helvetica,sans-serif}" +
    ".b{display:flex;align-items:center;justify-content:center;gap:10px;width:$($b.l)px;height:48px;box-sizing:border-box;border-radius:12px;background:#fff;font-size:16px;color:#191919;white-space:nowrap}</style>$($b.html)"
  $f = "$tmp\$($b.nom).html"
  Set-Content -LiteralPath $f -Value $page -Encoding utf8
  $png = "$racine\frontend\public\img\email\$($b.nom).png"
  $a = @("--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2", "--default-background-color=00000000",
    "--window-size=$($b.l),48", "--user-data-dir=$tmp\profil", "--allow-file-access-from-files", "--screenshot=$png", "file:///" + $f.Replace('\', '/'))
  Start-Process -FilePath "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" -ArgumentList $a -Wait | Out-Null
  "$($b.nom) : $(Test-Path $png)"
}
