<script setup>
import { computed } from "vue";

const props = defineProps({
  state: { type: Object, required: true },
  drafts: { type: Object, required: true },
});

const emit = defineEmits(["login"]);

const loginHint = computed(() => {
  const config = props.state.runtimeConfig;
  const redis =
    config?.cache_store === "redis"
      ? config.cache_ready
        ? "Redis 已连接，登录 token 会缓存 1 天。"
        : "Redis 未连接，账号登录会被拒绝，请先启动 Redis。"
      : "Redis 未启用，账号登录会被拒绝。";
  return `请输入用户名和密码登录。账号存储在 SQLite，登录 token 存储在 Redis。${redis}`;
});
</script>

<template>
  <section class="login-screen" aria-label="登录">
    <div class="login-copy">
      <p class="eyebrow">Boundary Login</p>
      <h1>先登录，再进入知识库边界</h1>
      <p>
        每个用户都会进入独立工作区：最近知识库、历史对话、前端缓存和操作视图都按用户、租户、权限标签隔离。
      </p>
      <div class="login-points">
        <span>SQLite 用户表</span>
        <span>Redis Token 1 天</span>
        <span>Tenant 隔离</span>
        <span>管理员 / 普通用户</span>
      </div>
    </div>

    <form class="login-card" @submit.prevent="emit('login')">
      <div>
        <p class="eyebrow">Sign In</p>
        <h2>登录到 BoundaryRAG</h2>
        <p class="login-hint">{{ loginHint }}</p>
      </div>

      <label>
        用户名
        <input v-model="drafts.login.username" autocomplete="username" placeholder="lcz10086" />
      </label>

      <label>
        密码
        <input
          v-model="drafts.login.password"
          autocomplete="current-password"
          placeholder="请输入密码"
          type="password"
        />
        <small class="field-hint">默认账号：lcz10086 / lcz123456，rag_user / rag_user123456。</small>
      </label>

      <button class="full" type="submit">登录并进入系统</button>
    </form>
  </section>
</template>
