<div align="center">
  <img src="assets/lead-link.png" width="96" height="96" alt="Иконка Lead Link">
  <h1>Lead Link Core</h1>
  <p>Зафиксированные исходники Xray, нативный мост и адаптер проверок Lead Link.</p>
  <p><a href="README.md">English</a> · <strong>Русский</strong></p>
  <p><a href="https://lead-link.app/">Сайт</a> · <a href="https://lead-link.app/support/">Поддержка</a> · <a href="https://github.com/pineapplesqueez/lead-link-core-source/releases">Релизы исходников</a></p>
  <p><strong>iOS · macOS · tvOS</strong></p>
</div>

---

Репозиторий содержит соответствующие исходники компонентов ядра, используемых в **Lead Link**. Его поддерживает **ADAPTA SIA**. В пакет входят исходники ядра VPN-туннеля и изменённое ядро для параллельной проверки задержки профилей.

В этом снимке собраны исходники Xray-core и libXray v26.11.9 для VPN-расширения Lead Link и адаптера проверки задержки.

> Это пакет исходников ядра, а не полное приложение Lead Link и не готовый к установке VPN-клиент. Интерфейс приложения, слой хранения и реализация передачи на TV в пакет не входят.

## Состав репозитория

| Путь | Содержимое |
| --- | --- |
| [Xray-core-original](Xray-core-original/) | Исходный релиз Xray-core. |
| [Xray-core-tunnel](Xray-core-tunnel/) | Исходники туннеля с исправлениями двух файлов Observatory. |
| [libXray](libXray/) | Нативный мост upstream и Invoke API. |
| [Xray-core-probe](Xray-core-probe/) | Xray-core с уже применёнными изменениями для изоляции проверок Lead Link. |
| [ProbeCore](ProbeCore/) | Go-адаптер проверок приложения, тесты, патч и хеши исходных upstream-файлов. |
| [build-scripts](build-scripts/) | Скрипты подготовки зафиксированного инструментария, сборки, проверки и сбора лицензий. |
| [ThirdPartyNotices.txt](ThirdPartyNotices.txt) | Уведомления о лицензиях зависимостей ядра, Go и геоданных. |
| [SHA256SUMS.json](SHA256SUMS.json) | SHA-256 каждого файла пакета, кроме самого манифеста. |

## Зафиксированные версии

| Компонент | Версия |
| --- | --- |
| Xray-core | **v26.11.9** · коммит [`676eaf66f8f0`](https://github.com/XTLS/Xray-core/commit/676eaf66f8f0) |
| libXray | **v26.11.9** · коммит [`5a0f7d8d1c28b34afb5727b04b26a10f6dbac7e3`](https://github.com/XTLS/libXray/commit/5a0f7d8d1c28b34afb5727b04b26a10f6dbac7e3) |
| Go | **1.27.4** |
| GeoIP Lite / GeoSite | [Xray-rules-dat 20261127013728](https://github.com/XTLS/Xray-rules-dat/releases/tag/20261127013728) |
| Патч Xray | В ProbeCore изменены 9 файлов. Два исправления Observatory также входят в туннель. |

Точные данные находятся в [upstream.lock.json](upstream.lock.json), [modules.lock.txt](modules.lock.txt) и [go-toolchain.lock.json](go-toolchain.lock.json). Они фиксируют исходники и граф зависимостей; сборка не следует за upstream-веткой `main`.

## Туннель и проверка задержки

VPN-расширение использует upstream libXray. В Xray-core исправлена синхронизация снимков статусов и отчётов об ошибках Observatory.

**Приложение → ProbeCore / изолированный Xray-core.** Для проверки задержки запускаются отдельные полные профили: у каждого собственный локальный SOCKS-слушатель, DNS, маршрутизация и наблюдатели. Патч изолирует состояние и завершение экземпляров; правила маршрутизации и стратегии балансировщиков не подменяются. Поэтому прямой маршрут в профиле может дать результат проверки через прямое соединение.

Приложение и расширение работают в разных процессах, в каждом — один Go runtime. На macOS приложению требуется `com.apple.security.network.server` для локального слушателя с авторизацией, используемого проверкой. Ограничения, жизненный цикл и детали sandbox описаны в [технической документации ProbeCore](ProbeCore/README.md) на английском.

Изменения можно изучить в [патче изоляции](ProbeCore/isolation.patch), сверить с [хешами исходных файлов](ProbeCore/upstream-files.json) или сравнить два дерева Xray:

```sh
git diff --no-index -- Xray-core-original Xray-core-probe
```

Код завершения `1` ожидаем, если `git diff` обнаружил описанные различия.

## Проверка снимка исходников

Выполните команду из корня распакованного пакета или локальной копии репозитория:

```sh
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

expected = json.loads(Path("SHA256SUMS.json").read_text())
failed = [name for name, digest in expected.items()
          if not Path(name).is_file()
          or hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest]
if failed:
    raise SystemExit("Missing or changed files:\n" + "\n".join(failed))
print(f"Verified {len(expected)} files.")
PY
```

Записи происхождения [LibXray](LibXray.xcframework.provenance.json) и [ProbeCore](ProbeCore.xcframework.provenance.json) содержат параметры первоначальной сборки и хеши её артефактов. Локально пересобранные бинарные файлы могут отличаться из-за инструментария и окружения; манифест исходников проверяет именно снимок исходного кода.

## Сборка компонентов ядра

Скрипт подготовки инструментария рассчитан на **macOS с Apple Silicon**. Нужны **Python 3.12+**, выбранная установка Xcode с SDK iOS, macOS и tvOS, а также доступ к сети для загрузки зафиксированных инструментов и Go-зависимостей. Записанная сборка использовала Xcode 27.2; минимальные версии ОС проверяет `verify-core.py`.

Скрипты ожидают структуру каталогов рабочего проекта приложения. Создайте отдельный каталог сборки, чтобы её результаты не меняли этот снимок исходников.

<details>
<summary><strong>Подготовка каталогов и команды сборки</strong></summary>

Из корня этого репозитория:

```sh
build_dir="$(mktemp -d "${TMPDIR:-/tmp}/lead-link-core-build.XXXXXX")"
mkdir -p "$build_dir/Core" "$build_dir/scripts"
cp -R ProbeCore "$build_dir/Core/ProbeCore"
cp -R Tests "$build_dir/Core/Tests"
cp -R GeodataLicenses "$build_dir/Core/GeodataLicenses"
cp upstream.lock.json modules.lock.txt licenses.lock.json \
  go-toolchain.lock.json geodata.lock.json "$build_dir/Core/"
cp build-scripts/*.py "$build_dir/scripts/"
cd "$build_dir"
```

Загрузите и проверьте зафиксированный инструментарий и полный официальный архив libXray, затем соберите оба варианта ядра:

```sh
python3 scripts/bootstrap-go.py
python3 scripts/fetch-core.py
python3 scripts/verify-upstream.py
python3 scripts/build-core.py --go .cache/toolchains/go-1.27.4/go/bin/go --test-observatory
python3 scripts/build-core.py --go .cache/toolchains/go-1.27.4/go/bin/go
python3 scripts/verify-core.py
python3 scripts/build-probe-core.py --test --race
python3 scripts/build-probe-core.py
python3 scripts/verify-core.py --probe
```

`build-core.py` загружает и проверяет зафиксированные Go-модули. `build-probe-core.py` применяет патч изоляции в каталоге сборки, сохраняя исходники туннеля без изменений.

Результат — `Artifacts/LibXray.xcframework` и `Artifacts/ProbeCore.xcframework`, а также записи происхождения сборки. Каждый XCFramework содержит пять вариантов SDK и восемь сочетаний платформы и архитектуры.

</details>

Дополнительные сведения — в [описании интеграции](INTEGRATION.md) и [документации ProbeCore](ProbeCore/README.md) на английском. Некоторые упомянутые там проверки приложения требуют отдельного рабочего проекта. В этот пакет не входят Xcode-проект приложения, данные подписи Apple, готовые фреймворки или инструментарий для полностью автономной сборки без сети.

## Лицензии и авторство

- **Xray-core:** [MPL-2.0](Xray-core-original/LICENSE). Девять изменённых файлов Xray также распространяются под [MPL-2.0](Xray-core-probe/LICENSE), с сохранением существующих уведомлений.
- **libXray:** [MIT](libXray/LICENSE).
- **Остальные компоненты:** см. [ThirdPartyNotices.txt](ThirdPartyNotices.txt), [licenses.lock.json](licenses.lock.json), [GeodataLicenses](GeodataLicenses/) и уведомления в отдельных файлах. Репозиторий не назначает одну общую лицензию всем компонентам.

Изменённые исходники Xray опубликованы непосредственно, вместе с патчем и оригинальной версией. Публикация этого пакета не предоставляет лицензию на отдельный исходный код приложения Lead Link или его фирменное оформление. Разъяснения по распространению MPL-кода — в [Mozilla MPL FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/).

## История снимков

| Снимок | Содержание |
| --- | --- |
| [core-26.11.9-observatory.1](https://github.com/pineapplesqueez/lead-link-core-source/tree/core-26.11.9-observatory.1) | Исходники сборки 14 для iOS, macOS и tvOS с исправлениями Observatory в PacketTunnel. |
| [core-26.11.9](https://github.com/pineapplesqueez/lead-link-core-source/tree/core-26.11.9) | Xray-core и libXray 26.11.9, Go 1.27.4 и соответствующий патч ProbeCore. |
| [build-1.1.0-10](https://github.com/pineapplesqueez/lead-link-core-source/tree/build-1.1.0-10) | Исходники для Lead Link iOS 1.1.0 (10). |
| Обновление документации · 20 ноября 2026 | README на английском и русском, оформление репозитория и пояснение о разрешении для локального слушателя macOS. Код ядра не менялся. |
| [source-audit-2026-11-17](https://github.com/pineapplesqueez/lead-link-core-source/releases/tag/source-audit-2026-11-17) | Дополнен состав исходников и уведомлений о вложенных зависимостях; возвращены файлы, скрытые upstream-правилами исключения. |
| [build-0.1.0-4](https://github.com/pineapplesqueez/lead-link-core-source/tree/build-0.1.0-4) | Исторический снимок исходников, сохранённый для прослеживаемости. |

Теги обозначают снимки исходников; их названия не обязательно совпадают с последней версией приложения. Исторические теги и архивы релизов сохраняют документацию, которая была опубликована вместе с ними.

## Поддержка

По вопросам Lead Link обращайтесь в [поддержку](https://lead-link.app/support/). В сообщении о проблеме ядра укажите коммит или тег исходников, платформу и минимальную конфигурацию без учётных данных. Не публикуйте в открытых issues ссылки подписок, ключи, пользовательские профили и данные подписи Apple.
