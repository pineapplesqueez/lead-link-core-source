# Интеграция upstream-ядра — E1

Закреплённая пара: libXray `7fe8528063e54343af8ba9a37431afc56000de21` и Xray-core `26.10.31`, соответствующий его go.mod. Go `1.27.3`. VPN-расширения используют неизменённый upstream. Приложение использует отдельный ProbeCore с адаптером и новым overlay для трёх параллельных полных профилей; [исходники, границы и сборка](ProbeCore/README.md). В каждом процессе ровно одна копия Go runtime. Системный VPN и проверки работают в разных процессах. Уже работающий managed core в процессе приложения не останавливается ради пробы.

## Воспроизводимая сборка

Из корня репозитория на Apple Silicon Mac с Xcode и Python 3.12+. Проверенное окружение: Xcode 27.2, macOS 27.2. Закреплённый Go устанавливается локально, без изменения системного Go:

```sh
python3 scripts/bootstrap-go.py
# Только при отсутствии Vendor/libXray:
python3 scripts/fetch-core.py
python3 scripts/verify-upstream.py
python3 scripts/build-core.py --go .cache/toolchains/go-1.27.3/go/bin/go
python3 scripts/verify-core.py
python3 scripts/build-probe-core.py
python3 scripts/verify-core.py --probe
python3 scripts/collect-core-licenses.py --go .cache/toolchains/go-1.27.3/go/bin/go
./scripts/verify.sh
```

`bootstrap-go.py` скачивает официальный архив по HTTPS, сверяет SHA-256 из `go-toolchain.lock.json` и устанавливает Go в `.cache/toolchains/go-1.27.3`. Повторный запуск сверяет receipt, хеш исполняемого файла и версию. Кэш находится в проекте и не зависит от очистки `/private/tmp` после обновления ОС. `fetch-core.py` проверяет SHA-256 архива, go.mod и go.sum. `verify-upstream.py` сравнивает все 86 файлов с официальным архивом, отказывается от изменённого исходного кода. `build-core.py` выполняет эту проверку до импорта Python-модулей upstream, проверяет версию Go, использует `GOTOOLCHAIN=local`, `GOWORK=off`, `go mod download/verify` и точное совпадение графа с `modules.lock.txt` перед компиляцией и после неё. Кэши по умолчанию находятся в `.cache/core`; их можно переопределить через `GOMODCACHE`/`GOCACHE`.

Повторно используются официальные target definitions, compiler flags, C bridge и упаковка AppleGoBuilder. Локальная оболочка заменяет изменяющие зависимости `go get`/`go mod tidy` на проверку закреплённого графа и отключает загрузку geo-данных: E1 их не использует. В E5 геобазы добавляются отдельно через `scripts/prepare-geodata.py`: версия архива и SHA-256 зафиксированы в `Core/geodata.lock.json`, данные включаются в bundle расширения, а с E5.1 также приложения для проверки профилей; подписка не управляет их загрузкой. Это изменение процесса сборки, а не патч ядра. Обновление зависимостей требует нового аудита и device regression.

Результат — `Artifacts/LibXray.xcframework`, пять SDK-вариантов и восемь сочетаний платформы/архитектуры: iOS arm64; iOS Simulator arm64/x86_64; macOS arm64/x86_64; tvOS arm64; tvOS Simulator arm64/x86_64. Provenance содержит версии инструментов, граф модулей и хеши всех файлов. `verify-core.py` проверяет фактические Mach-O платформы, архитектуры, минимальные OS, C ABI и хеши. `Artifacts` и `Vendor` исключены из Git.

## Пакетный путь и жизненный цикл

`NEPacketTunnelFlow` → Swift `PacketFlowBridge` → собственная пара AF_UNIX/SOCK_DGRAM → upstream TUN → Xray outbound. Адаптер передаёт четырёхбайтовый Darwin AF-заголовок, ограничивает размер пакетов/очереди и обрабатывает backpressure. Он выборочно перенесён из старого приложения и повторно проверен. KVC, поиск utun-дескрипторов, старый XrayBridge, gomobile и старые Go-патчи не используются. HEV остаётся резервным вариантом при выявленном ограничении; текущие проверки не дали причины добавлять второй стек.

`XrayEngine` вызывает `CGoInvoke`/`CGoFree`, Invoke API v3; каждый ненулевой ответ освобождается. Вызовы сериализованы общей блокировкой процесса. Необработанные сообщения ядра, способные содержать ключи, наружу не передаются. Logging конфигурации выключен; компилятор v2 также принудительно выключает REALITY `show`, включая вложенные XHTTP-настройки, поскольку этот отладочный вывод обходит обычный logger.

`TunnelLifecycle` сериализует подготовку, запуск и очистку, отклоняет повторный start и отменяет ожидающий запуск при stop. Поздний callback настройки сети сначала завершается, затем настройки очищаются. При остановке сначала закрывается ядро с его дубликатом дескриптора, затем Swift-адаптер и настройки NE.

`TunnelConfiguration` — внутренний доверенный контракт E1, передаваемый через startTunnel options, не подписка и не пользовательский импорт. Runtime сам создаёт корневые env/log/inbounds и единственный proxy outbound. Проверка корневых полей outbound **не является полной валидацией вложенных настроек**. Перед E3 нужны нормализованная модель, ограничения файловых/сетевых опций и обработка недоверенного полного Xray JSON. Отсутствие конфигурации завершает start ошибкой.

## Повторение тестов

```sh
python3 scripts/build-core.py --go .cache/toolchains/go-1.27.3/go/bin/go --mac-only --test-server
python3 scripts/build-probe-core.py --mac-only
python3 scripts/build-probe-core.py --test --race
python3 scripts/verify-runtime.py --xray Artifacts/TestServer/xray
python3 scripts/verify-runtime.py --xray Artifacts/TestServer/xray --security reality
```

Native-проверки выполняются на Apple Silicon Mac. Тестовый сервер слушает только loopback, использует синтетический UUID и временные ключи. TCP/UDP/DNS-ответы создаются локальными fixtures; реальные подписки не нужны. Reality target использует временный TLS 1.3 RSA-сертификат с X25519 и ALPN. Все слушатели закрываются после тестов.

Подписанная системная проверка macOS запускается отдельно и требует права на VPN-конфигурацию. DEBUG-only `E1Probe` ограничивает маршруты адресами `198.51.100.1/32` и `2001:db8::1/128`, не меняет DNS, удаляет созданную конфигурацию. Она проверяет фактический IPv4 TCP/UDP через NE. Проверки native IPv6/DNS не заменяют системные проверки IPv6/DNS/default route на устройствах.

Сценарии и ограничения: [отчёт E1](../docs/E1-VALIDATION.md). Успешная сборка или статус connected не заменяют передачу пакетов. E1 остаётся открытым до прохождения device matrix, оценки памяти/CPU и сетевых переходов.

## Лицензии и источники

В `App/Resources/ThirdPartyNotices.txt` включены уведомления 49 компонентов: Go, libXray и зависимости, достижимые для текущих Apple-сборок. `licenses.lock.json` хранит версии, пути и хеши исходных лицензий. Это автоматизированный сбор root LICENSE/NOTICE; перед выпуском нужен аудит полноты пакетных уведомлений. Публичная лицензия собственного приложения пока не выбрана.

- [libXray, закреплённый MIT upstream](https://github.com/XTLS/libXray/tree/7fe8528063e54343af8ba9a37431afc56000de21).
- [Xray-core, MPL-2.0](https://github.com/XTLS/Xray-core/tree/a4a3dff5b20c).
- [Upstream переход TUN-стека](https://github.com/XTLS/Xray-core/pull/7130).
- [Apple: назначение Packet Tunnel Provider](https://developer.apple.com/documentation/technotes/tn3120-expected-use-cases-for-network-extension-packet-tunnel-providers).

## Готовые фреймворки

Собранные `LibXray.xcframework` и `ProbeCore.xcframework` не хранятся в Git: это ~300 МБ на каждый и они воспроизводимо собираются из закреплённых исходников. Их zip-архивы лежат в приватном GitHub Release; тег и SHA-256 записаны в `Core/prebuilt.lock.json`.

- `python3 scripts/fetch-prebuilt-core.py` — скачать, сверить SHA-256 и распаковать в `Artifacts/`.
- `python3 scripts/publish-core.py` — после пересборки любого ядра выложить новый релиз и обновить lock; затем закоммитить `Core/prebuilt.lock.json`.

LibXray — неизменённый upstream; ProbeCore содержит app-only overlay (см. `Core/ProbeCore/README.md`), его соответствующие исходники распространяются пакетом `scripts/package-open-source.py`.
