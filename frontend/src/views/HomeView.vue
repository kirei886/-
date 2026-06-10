<script setup lang="ts">
// 占位首页：证明 Vue + 路由骨架跑通。
// 已落地「路线结果页」(/plan)，其余业务页待 MasterGo 设计稿逐页实现。
</script>

<template>
  <main class="home">
    <h1>企业班车路径规划</h1>
    <p>前端脚手架已就绪，业务页面逐步实现中。</p>
    <RouterLink class="entry" to="/plan">进入路线规划 →</RouterLink>
  </main>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 8px;
  color: #1f2329;
}

.home h1 {
  font-size: 24px;
  font-weight: 600;
}

.home p {
  color: #646a73;
}

.entry {
  margin-top: 8px;
  padding: 8px 18px;
  border-radius: 6px;
  background: #e1372e;
  color: #fff;
  font-size: 14px;
  text-decoration: none;
}
</style>
