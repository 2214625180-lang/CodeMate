<script setup>
import { computed } from "vue";
import { buildUserLabel } from "../composables/useUserLabel";

const props = defineProps({
  user: {
    type: Object,
    required: true
  }
});

const label = computed(() => buildUserLabel(props.user));
</script>

<template>
  <span class="user-badge">{{ label }}</span>
</template>
