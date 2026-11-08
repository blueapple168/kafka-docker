<p align="center">
<picture>
  <source media="(prefers-color-scheme: light)" srcset="docs/images/kafka-logo-readme-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/kafka-logo-readme-dark.svg">
  <img src="docs/images/kafka-logo-readme-light.svg" alt="Kafka Logo" width="50%">
</picture>
</p>

# Apache Kafka 国产化（信创）镜像构建分支

[![CI](https://github.com/blueapple168/kafka-docker/actions/workflows/ci.yml/badge.svg?branch=trunk&event=push)](https://github.com/blueapple168/kafka-docker/actions/workflows/ci.yml?query=event%3Apush+branch%3Atrunk)
[![Docker Build and Publish (UOS)](https://github.com/blueapple168/kafka-docker/actions/workflows/docker_build_and_publish_uos.yml/badge.svg?branch=trunk)](https://github.com/blueapple168/kafka-docker/actions/workflows/docker_build_and_publish_uos.yml?query=branch%3Atrunk)

本仓库是 [apache/kafka](https://github.com/apache/kafka) 的衍生分支（fork）。在上游 `trunk` 源码的基础上，增加了面向**国产操作系统 / 信创环境**的容器镜像构建与发布能力：

- 基础镜像使用 **统信 UOS Server 20（1070a，RHEL 8 兼容，glibc 2.28）**，替换官方镜像的 Alpine（musl）；
- 提供 **jvm** 与 **native**（GraalVM AOT）两种变体；
- 同时产出 **linux/amd64** 与 **linux/arm64**（鲲鹏 / 飞腾 / 海光等国产 CPU 常用架构），合成多架构 manifest；
- 上游源码、Gradle 构建体系与测试体系**保持不变**，可继续合并 `apache:trunk`。

上游英文文档仍适用于开发构建场景，见文末「开发构建」章节与 [docs/](docs/)。

---

## 一、已发布镜像

镜像仓库：`ghcr.io/blueapple168/kafka`

<!-- IMAGE-TAGS:BEGIN -->
| 镜像 tag | 变体 | Kafka 版本 | 平台 | Digest（前 16 位） | 构建完成（UTC） |
| --- | --- | --- | --- | --- | --- |
| `4.3.1-native-uos` | native | 4.3.1 | linux/amd64, linux/arm64 | `sha256:dfa5cceda94998f7` | 2026-11-08 08:07 |
| `4.3.1-uos` | jvm | 4.3.1 | linux/amd64, linux/arm64 | `sha256:5be87d81e2817f0a` | 2026-11-08 07:58 |
<!-- IMAGE-TAGS:END -->

> 上表由流水线在镜像发布成功后自动写入（见 [5.4 README 维护约定](#54-readme-维护约定)），请勿手工修改表格内容。

| 变体 | 说明 | 适用场景 |
| --- | --- | --- |
| `jvm`（tag 形如 `4.3.1-uos`） | 内置 Temurin JRE 25，Kafka 以 JVM 方式运行，附 CDS 归档（`kafka.jsa` / `storage.jsa`）加速启动 | 通用生产环境，兼容性与可观测性最好 |
| `native`（tag 形如 `4.3.1-native-uos`） | GraalVM native-image 预编译的 `kafka.Kafka` 二进制，镜像内无 JDK/JRE | 追求启动速度与更小内存占用，接受更长的构建时间 |

---

## 二、与官方镜像的差异

| 维度 | 官方 `apache/kafka` | 本仓库 UOS 镜像 | 差异原因 |
| --- | --- | --- | --- |
| 基础镜像 | `eclipse-temurin:25-jre-alpine` | `ghcr.io/blueapple168/uos-server-20-1070a:latest` | 信创环境要求国产 OS 底座 |
| C 运行库 | musl libc | glibc 2.28 | 与国产 OS 一致，无需 `gcompat` 兼容层 |
| 包管理 | `apk add` | `yum`（单次会话合并安装 + 失败退避重试） | UOS 使用 RHEL 8 系包管理 |
| JDK / JRE 来源 | 基础镜像内置 | Adoptium Temurin tarball 离线解压至 `/usr/lib/jvm` | 避免 UOS 源内 JDK 版本过旧，同时保留 SHA256 校验 |
| 时区 / 编码 | 未设置 | `TZ=Asia/Shanghai`、`LANG=C.UTF-8` | 规避国内环境下的 latin1 编码告警与时间偏移 |
| 运行用户 | `appuser`（UID 1000） | 同名 `appuser`（UID/GID 冲突时回退系统分配） | 保持非 root 运行，符合等保三级要求 |
| 体积优化 | 仅 CDS | CDS + 运行时阶段仅装 JRE（约省 100MB） | 缩短拉取时间，适配内网带宽 |
| 供应链校验 | Kafka tarball 的 PGP 签名 | Kafka PGP 签名 + Temurin SHA256（镜像源 + 官方摘要双源校验） | 国产化交付需可追溯的完整性证据 |

镜像内部结构：

| 项 | 值 |
| --- | --- |
| 监听端口 | `9092`（PLAINTEXT broker）、`9093`（KRaft controller） |
| 配置目录 | `/etc/kafka`、`/etc/kafka/docker` |
| 证书目录 | `/etc/kafka/secrets`（声明为卷，建议挂载） |
| 共享配置 | `/mnt/shared/config`（声明为卷，建议挂载） |
| 数据目录 | **jvm**：`/var/lib/kafka/data`（声明为卷，建议挂载）<br>**native**：未声明数据卷，默认 `log.dirs=/tmp/kraft-combined-logs`，需持久化时设置 `KAFKA_LOG_DIRS` 并挂载 |
| 入口命令 | `/etc/kafka/docker/run`（→ `configure` → `launch`） |
| 运行用户 | `appuser`（UID 1000） |

---

## 三、快速开始

### 3.1 单机（KRaft 合并模式，一条命令）

```bash
docker run -d --name kafka \
  -p 9092:9092 \
  -e KAFKA_NODE_ID=1 \
  -e KAFKA_PROCESS_ROLES=broker,controller \
  -e KAFKA_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093 \
  -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://<宿主机IP>:9092 \
  -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
  -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@localhost:9093 \
  -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
  -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1 \
  -e KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1 \
  -e KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS=0 \
  -e KAFKA_LOG_DIRS=/var/lib/kafka/data \
  -v kafka-data:/var/lib/kafka/data \
  ghcr.io/blueapple168/kafka:4.3.1-uos
```

> `KAFKA_ADVERTISED_LISTENERS` 必须填客户端**真实可达**的地址（容器内 `localhost` 只能用于同容器访问）。
> 未显式设置 `CLUSTER_ID` 时使用镜像内置默认值；生产环境建议显式指定，集群内保持一致。

### 3.2 Docker Compose

仓库内已提供可直接复用的编排样例（含 plaintext / sasl_plaintext / ssl、单机与集群）：

```bash
cd docker/examples/docker-compose-files/single-node/plaintext
IMAGE=ghcr.io/blueapple168/kafka:4.3.1-uos docker compose up -d
```

完整样例清单见 [docker/examples/README.md](docker/examples/README.md)。

### 3.3 验证

```bash
docker exec -it kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
docker exec -it kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --topic demo --partitions 1 --replication-factor 1
```

---

## 四、镜像设计要点

1. **两阶段构建**：`build-jsa` 阶段装 JDK 生成 CDS 归档，`runtime` 阶段只装 JRE 并 `COPY --from` 归档，兼顾启动速度与体积。
2. **Temurin 走 tarball 而非系统包**：UOS 源内 JDK 版本往往滞后，改为从镜像站下载 Adoptium tarball 并做 SHA256 校验，版本与校验和由流水线自动解析（详见 5.3）。
3. **Kafka tarball 走 PGP 校验**：下载 `.asc` 签名并用 Apache 官方 `KEYS` 验签，`KEYS` 支持 archive/downloads/dlcdn/清华/阿里云 五路回退。
4. **失败可诊断**：yum 安装带 3 轮指数退避；tarball 下载失败会打印完整 URL 与「镜像可能已轮转补丁版本」的提示，不再只留一个 `exit 1`。
5. **非 root 运行**：`appuser` 拥有数据与配置目录写权限，`/etc/kafka` 组权限为 `ug+w`，满足只读根文件系统的挂载需求。

---

## 五、构建与发布

### 5.1 通过 GitHub Actions（推荐）

工作流：`.github/workflows/docker_build_and_publish_uos.yml`

| 触发方式 | 条件 |
| --- | --- |
| 自动 | push 到 `trunk`，且改动命中 `docker/jvm/**`、`docker/native/**`、`docker/launch`、`docker/jsa_launch`、`docker/server.properties`、`docker/common-scripts/**`、`docker/resources/**` 或本工作流文件 |
| 手动 | `workflow_dispatch`，可选覆盖 `kafka_url` 与 `image_tag` |

> `update-readme` 仅在 `trunk` 分支且构建与 manifest 合并均成功时执行；其他分支或部分平台失败时不会写入文档。

流水线结构（matrix 拆分为独立 job，互不牵连）：

```
build-and-publish (variant × platform)     merge-manifest (variant)      update-readme
  jvm    × amd64  →  ${tag}-amd64   ┐
  jvm    × arm64  →  ${tag}-arm64   ├→  合成 multi-arch manifest  →   写入 README 镜像清单
  native × amd64  →  ${tag}-amd64   │      ghcr.io/...:${tag}
  native × arm64  →  ${tag}-arm64   ┘
```

- arm64 使用原生 `ubuntu-24.04-arm` runner，不走 QEMU 模拟（QEMU 下 native-image 编译可达数小时）。
- 每个 job 完成后执行 Trivy 扫描（CRITICAL/HIGH），报告作为 artifact 上传；`exit-code: 0`，即**扫描不阻断发布**，由人工审查。

### 5.2 本地构建

```bash
# jvm 变体（本地手动构建时才需要手工指定版本与摘要）
cd docker
touch kafka.tgz          # 占位：满足 Dockerfile 中 COPY *kafka.tgz 的 glob
docker buildx build \
  -f jvm/Dockerfile-uos \
  --build-arg KAFKA_VERSION=4.3.1 \
  --build-arg kafka_url=https://archive.apache.org/dist/kafka/4.3.1/kafka_2.13-4.3.1.tgz \
  --build-arg JDK_VERSION=25.0.5_8 \
  --build-arg JRE_VERSION=25.0.5_8 \
  -t kafka:4.3.1-uos --load .
```

```bash
# native 变体（不依赖 Temurin；GraalVM native-image 编译耗时较长，
# 建议在 arm64/amd64 原生机器上构建，不要用 QEMU 跨架构模拟）
docker buildx build \
  -f native/Dockerfile-uos \
  --build-arg KAFKA_VERSION=4.3.1 \
  --build-arg kafka_url=https://archive.apache.org/dist/kafka/4.3.1/kafka_2.13-4.3.1.tgz \
  -t kafka:4.3.1-native-uos --load docker/
```

> 基础镜像可用 `--build-arg BASE_IMAGE_TAG=<repo>:<tag>` 替换；JDK 镜像站可用 `--build-arg JAVA_MIRROR_BASE_URL=...` 替换（华为云 / 阿里云等）。
> 本地构建未传 `JDK_TARBALL_SHA256_*` / `JRE_TARBALL_SHA256_*` 时，Dockerfile 只告警并跳过 SHA256 校验（CI 会自动解析并强制校验）。

### 5.3 新版本发布流程

发布新 Kafka 版本时，**必须构建镜像并同步 README**，按以下顺序执行：

| 步骤 | 操作 | 说明 |
| --- | --- | --- |
| 1 | 修改 `docker_build_and_publish_uos.yml` 中的 `KAFKA_VERSION` | 版本号集中维护，仅此一处 |
| 2 | push 到 `trunk`，或手动触发 `workflow_dispatch` | 手动触发可同时指定 `kafka_url`（如内网归档地址） |
| 3 | 流水线自动解析 Temurin 版本与 SHA256 | 从镜像目录页取版本、从 Adoptium 官方 API 取摘要，**无需手工维护 4 个 Secrets** |
| 4 | 构建 → 推送 → 合成多架构 manifest | 产物 tag：`${KAFKA_VERSION}-uos` / `${KAFKA_VERSION}-native-uos` |
| 5 | `update-readme` job 自动更新 README 镜像清单 | 表格由脚本写入并提交，提交信息带 `[skip ci]` |

### 5.4 README 维护约定

README 中的镜像清单被一对标记包裹：起始标记 `<!-- IMAGE-TAGS:BEGIN -->` 与结束标记 `<!-- IMAGE-TAGS:END -->`，**两者之间的内容全部由脚本生成**。

- 脚本：`.github/scripts/update-readme.py`，纯标准库实现、幂等（内容无变化时不改文件，不产生空提交）。
- 自动：镜像发布成功后由 `update-readme` job 调用，用 `GITHUB_TOKEN` 提交并推送（GitHub 不会因此触发新的工作流运行）。
- 手工补录（例如内网单独构建、或流水线更新失败后补救；Windows 环境把 `python3` 写作 `python`）：

```bash
cat > /tmp/rows.json <<'JSON'
{
  "kafka_version": "4.3.1",
  "rows": [
    {
      "tag": "4.3.1-uos",
      "variant": "jvm",
      "platforms": "linux/amd64, linux/arm64",
      "digest": "sha256:5be87d81e2817f0a806efd53c6f9a2ded39606ace6d374c2a9abbd8b736f9796",
      "built_at": "2026-11-08 07:58"
    }
  ]
}
JSON
python3 .github/scripts/update-readme.py --data /tmp/rows.json
```

- 校验（不写文件，若有差异则以非 0 退出）：

```bash
python3 .github/scripts/update-readme.py --data /tmp/rows.json --check
```

除该区块外的文字说明（差异表、设计要点、流程等）仍需在版本变化时人工复核，例如：JDK 大版本升级、端口或目录变更、新增变体。

---

## 六、内网 / 离线构建

信创交付通常处于隔离网络，镜像构建可按以下方式收敛外部依赖：

| 外部依赖 | 可替换方式 |
| --- | --- |
| 基础镜像 `ghcr.io/blueapple168/uos-server-20-1070a` | 同步到内网 Harbor，用 `--build-arg BASE_IMAGE_TAG=<内网仓库>/uos-server-20-1070a:latest` |
| Temurin JDK / JRE tarball | `--build-arg JAVA_MIRROR_BASE_URL=<内网镜像站>/Adoptium/25`，并保持目录结构 `<jdk 或 jre>/<arch>/linux/` |
| Kafka tarball | 用 `workflow_dispatch` 的 `kafka_url` 指向内网归档，或本地构建时把 tarball 放在 `docker/kafka.tgz` |
| Apache `KEYS`（PGP 验签） | 已内置五路镜像回退；完全离线时需预置 `KEYS` 并调整 Dockerfile 中该步骤 |

完全离线构建提示：`kafka_url` 留空时 Dockerfile 会跳过下载与验签，直接解压 context 中已有的 `docker/kafka.tgz`。

---

## 七、与上游同步

```bash
git remote add apache https://github.com/apache/kafka.git   # 首次
git fetch apache trunk
git merge apache/trunk
```

合并时需重点关注的本地改动（避免被上游覆盖）：

| 文件 | 本地改动 | 冲突处理建议 |
| --- | --- | --- |
| `.github/workflows/build.yml` | `load-catalog` 增加 `test-catalog` 分支探测；`update-test-catalog` 增加 `!github.event.repository.fork` 守卫 | 保留本地守卫，否则 fork 无 `test-catalog` 分支会让整个 CI 报红 |
| `.github/workflows/ci-complete.yml` | build scan 空矩阵与 Develocity 未配置时跳过发布 | 保留，否则 `workflow_run` 会因空矩阵判负 |
| `README.md` | 本文件（国产化说明 + 镜像清单区块） | 冲突时**保留本地版本**，再手工补齐上游新增的开发构建章节 |
| `docker/jvm/Dockerfile-uos`、`docker/native/Dockerfile-uos` | 新增文件（上游无） | 一般不冲突 |

CI 现状：`test` 为 6 个矩阵 job（Java 25/17 × flaky/new），单次全量耗时较长；如需在 fork 上收敛成本，可裁剪 `build.yml` 的 matrix（本仓库暂未改动，保持上游语义）。

---

## 八、开发构建（上游能力，未改动）

需要 JDK 17 及以上。Kafka 以 Java 17 与 25 构建和测试，`clients`、`streams` 模块 `javac --release 11`，其余模块 `--release 17`；Scala 仅支持 2.13。

| 目的 | 命令 |
| --- | --- |
| 构建 JAR | `./gradlew jar` |
| 构建二进制发行包 | `./gradlew clean releaseTarGz`（产物在 `core/build/distributions/`） |
| 单元 + 集成测试 | `./gradlew test` |
| 单个测试类 | `./gradlew clients:test --tests RequestResponseTest` |
| 代码风格检查 | `./gradlew checkstyleMain checkstyleTest spotlessCheck` |
| 静态缺陷扫描 | `./gradlew spotbugsMain spotbugsTest -x test` |
| 生成测试覆盖率 | `./gradlew reportCoverage -PenableTestCoverage=true -Dorg.gradle.parallel=false` |
| 本地运行 broker | `KAFKA_CLUSTER_ID="$(./bin/kafka-storage.sh random-uuid)"` → `./bin/kafka-storage.sh format --standalone -t $KAFKA_CLUSTER_ID -c config/server.properties` → `./bin/kafka-server-start.sh config/server.properties` |

更多内容（IDE 配置、JMH 基准、系统测试、Trogdor、依赖分析、Gradle 升级、Maven 本地安装等）见：

- [docker/README.md](docker/README.md)：镜像构建脚本、RC 发布、CVE 扫描任务
- [docs/](docs/)：官方文档源；[tests/README.md](tests/README.md)：系统测试
- [jmh-benchmarks/README.md](jmh-benchmarks/README.md)、[trogdor/README.md](trogdor/README.md)、[vagrant/README.md](vagrant/README.md)、[examples/README.md](examples/README.md)

---

## 九、安全与合规

| 项 | 现状 |
| --- | --- |
| 镜像漏洞扫描 | Trivy 扫描 CRITICAL/HIGH，报告作为 workflow artifact 归档，不阻断发布 |
| 供应链完整性 | Kafka tarball PGP 验签 + Temurin SHA256 双源校验 |
| 运行权限 | 非 root（`appuser`，UID 1000），数据与配置目录最小授权 |
| 时间与编码 | `TZ=Asia/Shanghai`、`LANG/LC_ALL=C.UTF-8`，避免日志时间与中文乱码问题 |
| 部署可追溯 | 建议以 digest 而非浮动 tag 固定部署：`ghcr.io/blueapple168/kafka@sha256:...` |
| 等保三级相关 | 三权分立账户体系需在宿主机/编排层落实；容器内不内置多账户 |

---

## 十、许可证

本仓库继承上游许可证：[Apache License 2.0](LICENSE)。二进制发行物相关声明见 [NOTICE-binary](NOTICE-binary) 与 [LICENSE-binary](LICENSE-binary)。

上游社区贡献入口：[Contributing to Apache Kafka](https://kafka.apache.org/contributing.html)。
