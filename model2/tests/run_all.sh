#!/bin/sh
# Roda todos os testes (usam um MongoDB simulado em memória; não tocam no Atlas).
cd "$(dirname "$0")/.." || exit 1
for t in test_app test_admin test_ag test_final test_mail_ag test_login_hash; do
  echo "== $t"; python tests/$t.py > /tmp/$t.log 2>&1 && echo "passou" || { echo "FALHOU"; tail -5 /tmp/$t.log; exit 1; }
done
