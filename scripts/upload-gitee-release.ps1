# deepl-quick：把 dist 里最新的绿色包 zip 作为附件补传到 Gitee 发行版。
# 实测 GitHub 机房直传 Gitee 大文件必超时，附件必须走本地（国内）网络。
# 令牌来源（二选一）：仓库根目录 .gitee-token 文件（推荐，一次保存永久免输入）
#                     或运行时手动输入（可选保存）。令牌绝不入库、绝不写进脚本。
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$tokenFile = Join-Path $root '.gitee-token'

$zip = Get-ChildItem (Join-Path $root 'dist') -Filter 'deepl-quick-*.zip' -ErrorAction SilentlyContinue |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $zip) {
    Write-Host 'dist 文件夹里没有绿色包 zip。请先构建：'
    Write-Host '  python scripts\build_portable.py --embeddable-zip <python-embed.zip 路径>'
    exit 1
}

$ver = (Select-String -Path (Join-Path $root 'deepl_quick.pyw') -Pattern 'APP_VERSION = "([^"]+)"').Matches[0].Groups[1].Value
$tag = "v$ver"
if ($zip.Name -notlike "*$tag-*") {
    Write-Host "版本不匹配：dist 里最新的包是 $($zip.Name)，与 APP_VERSION 推出的目标发行版 $tag 不一致。"
    Write-Host "请先把 $tag 的绿色包放进 dist\，再重试。"
    exit 1
}
$notes = Join-Path $root 'dist\RELEASE.md'
$hasNotes = Test-Path $notes

Write-Host "即将上传：$($zip.Name)"
Write-Host "目标发行版：$tag （已存在则直接补附件）"

# —— 令牌读取：文件优先；若文件存在但未被 gitignore 保护，拒绝运行 ——
$token = $null
if (Test-Path $tokenFile) {
    git -C $root check-ignore -q '.gitee-token'
    if ($LASTEXITCODE -ne 0) {
        Write-Host '安全拦截：.gitee-token 存在但未被 .gitignore 忽略，为防泄露拒绝运行。'
        Write-Host '请确认 .gitignore 里有 .gitee-token 这一行后再试。'
        exit 1
    }
    $token = (Get-Content $tokenFile -Raw).Trim()
    if (-not $token) { $token = $null }
    else { Write-Host '已从 .gitee-token 读取令牌。' }
}
if (-not $token) {
    $token = Read-Host '请输入 Gitee 私人令牌（projects 权限）'
    if (-not $token) { Write-Host '未输入令牌，已取消。'; exit 1 }
    $ans = Read-Host '保存到 .gitee-token，下次免输入？(y/N)'
    if ($ans -eq 'y') {
        Set-Content -Path $tokenFile -Value $token -NoNewline -Encoding ascii
        Write-Host '已保存（该文件已被 .gitignore 忽略，不会进仓库）。'
    }
}

$env:GITEE_TOKEN = $token
if ($hasNotes) {
    python (Join-Path $here 'gitee_release.py') $tag $zip.FullName $notes
} else {
    python (Join-Path $here 'gitee_release.py') $tag $zip.FullName
}
Write-Host ''
Write-Host '输出显示 attached 即成功，可到 Gitee 发行版页面确认附件。'
