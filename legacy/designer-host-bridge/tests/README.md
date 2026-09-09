# tests/

## host/ — Host Bridge (отложенный вариант B, docs/SPEC.md п.4)
Появятся при реализации: unit-тесты allowlist/path-mapping, интеграционные тесты wrapper → bridge.

## integration/ — конвейер (вариант A)
Ручные сценарии PoC (чек-листы в docs/SPEC.md):

1. doctor: все PASS (включая licensing smoke).
2. migrate на тестовом хранилище 5–10 версий: 1 версия = 1 коммит,
   автор/дата/комментарий сохранены, порядок версий верный.
3. Конфигурация в Git — EDT-формат (DT-INF/PROJECT.PMF, .project, src/).
4. Изоляция: `git diff --name-only HEAD^ HEAD` ⊂ PROJECT_PATH.
5. Повторный sync без новых версий → 0 коммитов.
6. Новая версия → ровно 1 коммит.
7. Recovery: падение на версии N → продолжение с N (не с начала).
8. Push в Gitea, история не переписывается.
9. Устойчивость лицензии: restart / down-up / recreate контейнера → smoke PASS.
10. Failure modes: bridge offline (для B), платформа младше хранилища,
    неизвестный автор, недоступный git remote — понятные ошибки.
