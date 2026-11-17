# Lead Link — исходники компонентов ядра

Соответствующие исходники компонентов ядра Lead Link: оригинальный Xray-core и libXray для VPN-расширения и Xray-core с изменениями ProbeCore для проверки пинга. Публичный адрес: https://github.com/pineapplesqueez/lead-link-core-source — на него ссылается экран лицензий в приложении. Каждая сборка с изменённым ядром публикуется отдельным тегом. Исходники интерфейса Lead Link сюда не входят; их лицензия этим документом не выбирается.

`upstream.lock.json` фиксирует libXray, Xray-core и Go. `Xray-core-original` — исходный Xray для VPN extension; `Xray-core-probe` — тот же исходник с восемью изменёнными файлами для параллельных проверок. Точные исходные хеши и патч лежат в `ProbeCore/upstream-files.json` и `ProbeCore/isolation.patch`. Существующие авторские уведомления сохранены. Эти изменения Xray распространяются на условиях MPL-2.0; полный текст — `Xray-core-probe/LICENSE`. `libXray` содержит исходный мост. `ThirdPartyNotices.txt` содержит лицензии фактических зависимостей, Go и geodata; версии зависимостей закреплены в go.mod/go.sum и modules.lock.txt.

В пакете нет подписок, ключей, профилей пользователей, данных подписи Apple или исходников интерфейса. `SHA256SUMS.json` позволяет проверить каждый включённый файл. Изменённый код можно изучить непосредственно, без применения патча.

Для сборки нужны macOS, Xcode с SDK iOS/macOS/tvOS и Go версии из upstream.lock.json. Скрипты используют исходную структуру проекта: Core/ProbeCore, Core/*.lock.*, Vendor/libXray, .cache/core/modules и .cache/toolchains. Положите содержимое ProbeCore в Core/ProbeCore, lock-файлы в Core, libXray в Vendor/libXray, build-scripts в scripts; затем используйте инструкции INTEGRATION.md и ProbeCore/README.md. Go загружает неизменённые зависимости с проверкой go.sum. Пакет представляет соответствующие исходники; это не автономный offline toolchain и не готовый Xcode-проект приложения.

Проверка/повторная упаковка в рабочем репозитории:

```sh
python3 scripts/package-open-source.py --output Artifacts/OpenSource/LeadLink-core-source.tar.gz
```

Рекомендации MPL: https://www.mozilla.org/en-US/MPL/2.0/FAQ/ (в особенности Q9–Q12). Публикация исходников указанных компонентов не означает обязательного открытия всего интерфейса приложения.

## Обновление пакета от 17 ноября 2026 года

Тег `source-audit-2026-11-17` фиксирует исправление состава исходников и уведомлений о лицензиях; он не обозначает новую сборку приложения. Исторический тег `build-0.1.0-4` сохранён.

В `ThirdPartyNotices.txt` и `licenses.lock.json` добавлены уведомления из используемых вложенных пакетов, включая xxhash, dicttls и masque/connectip. `build-scripts/collect-core-licenses.py` собирает уведомления по графам зависимостей обоих ядер для Apple-архитектур. Исходники и тестовые данные, которые раньше скрывали вложенные `.gitignore`, теперь присутствуют в Git; генерируемый каталог `libXray/apple_xcframework` исключён из исходного пакета. `SHA256SUMS.json` перечисляет все файлы пакета, кроме самого манифеста.
