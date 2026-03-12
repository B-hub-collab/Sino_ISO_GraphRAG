#!/bin/bash
# ==========================================
# APOC 設置腳本
# ==========================================
# 用途：安裝和配置 Neo4j APOC 擴展以支持 Parquet 導入

set -e  # 遇到錯誤立即退出

echo "=========================================="
echo "APOC 設置腳本"
echo "=========================================="

# 配置變數（請根據實際環境修改）
NEO4J_HOME="${NEO4J_HOME:-/var/lib/neo4j}"
NEO4J_VERSION="${NEO4J_VERSION:-5.27.0}"
APOC_VERSION="${APOC_VERSION:-5.27.0}"

echo "Neo4j Home: $NEO4J_HOME"
echo "APOC Version: $APOC_VERSION"
echo ""

# 檢查 Neo4j 目錄
if [ ! -d "$NEO4J_HOME" ]; then
    echo "錯誤: Neo4j 目錄不存在: $NEO4J_HOME"
    echo "請設置環境變數 NEO4J_HOME 或修改腳本中的路徑"
    exit 1
fi

# 創建 plugins 目錄
mkdir -p "$NEO4J_HOME/plugins"

# 下載 APOC Extended
echo "下載 APOC Extended..."
APOC_JAR="apoc-${APOC_VERSION}-extended.jar"
APOC_URL="https://github.com/neo4j/apoc/releases/download/${APOC_VERSION}/${APOC_JAR}"

if [ -f "$NEO4J_HOME/plugins/$APOC_JAR" ]; then
    echo "  APOC Extended 已存在，跳過下載"
else
    wget -P "$NEO4J_HOME/plugins" "$APOC_URL" || {
        echo "錯誤: 下載 APOC Extended 失敗"
        echo "請手動下載: $APOC_URL"
        exit 1
    }
    echo "  下載完成: $APOC_JAR"
fi

# 下載 APOC Hadoop Dependencies（支持 Parquet）
echo "下載 APOC Hadoop Dependencies..."
APOC_HADOOP_JAR="apoc-hadoop-dependencies-${APOC_VERSION}.jar"
APOC_HADOOP_URL="https://github.com/neo4j/apoc/releases/download/${APOC_VERSION}/${APOC_HADOOP_JAR}"

if [ -f "$NEO4J_HOME/plugins/$APOC_HADOOP_JAR" ]; then
    echo "  APOC Hadoop Dependencies 已存在，跳過下載"
else
    wget -P "$NEO4J_HOME/plugins" "$APOC_HADOOP_URL" || {
        echo "錯誤: 下載 APOC Hadoop Dependencies 失敗"
        echo "請手動下載: $APOC_HADOOP_URL"
        exit 1
    }
    echo "  下載完成: $APOC_HADOOP_JAR"
fi

# 配置 Neo4j
echo "配置 Neo4j..."
NEO4J_CONF="$NEO4J_HOME/conf/neo4j.conf"

if [ -f "$NEO4J_CONF" ]; then
    # 檢查配置是否已存在
    if grep -q "apoc.import.file.enabled" "$NEO4J_CONF"; then
        echo "  配置已存在，跳過"
    else
        echo "" >> "$NEO4J_CONF"
        echo "# APOC Configuration" >> "$NEO4J_CONF"
        echo "apoc.import.file.enabled=true" >> "$NEO4J_CONF"
        echo "apoc.export.file.enabled=true" >> "$NEO4J_CONF"
        echo "  配置已添加到 neo4j.conf"
    fi
else
    echo "  警告: neo4j.conf 未找到，請手動配置"
    echo "  需要添加的配置："
    echo "    apoc.import.file.enabled=true"
    echo "    apoc.export.file.enabled=true"
fi

# 設置權限
echo "設置文件權限..."
chmod 644 "$NEO4J_HOME/plugins"/*.jar

echo ""
echo "=========================================="
echo "APOC 設置完成！"
echo "=========================================="
echo ""
echo "下一步："
echo "1. 重啟 Neo4j 服務："
echo "   sudo systemctl restart neo4j"
echo "   或"
echo "   $NEO4J_HOME/bin/neo4j restart"
echo ""
echo "2. 驗證 APOC 是否安裝成功："
echo "   在 Neo4j Browser 執行："
echo "   RETURN apoc.version()"
echo ""
