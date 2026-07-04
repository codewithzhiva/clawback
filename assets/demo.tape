# Clawback demo — records a live audit against a real AWS account.
# Regenerate: vhs assets/demo.tape  (needs AWS creds; scan is read-only)
Output assets/demo.gif
Set FontSize 14
Set Width 1000
Set Height 600
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

Hide
Type "export AWS_PROFILE=clawback && clear"
Enter
Show

Type "# find AWS money leaks — read-only, safety-verified"
Enter
Sleep 1s
Type "python3 scripts/collect/orphans.py --regions us-east-1 --out findings/orphans.json"
Enter
Sleep 12s
Type "python3 scripts/report.py --findings findings/orphans.json --out AUDIT_REPORT.md"
Enter
Sleep 2.5s
Type "head -45 AUDIT_REPORT.md"
Enter
Sleep 7s
