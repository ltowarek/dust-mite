export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'scope-enum': [
      2,
      'always',
      [
        'car',
        'controller',
        'web',
        'observability',
        'devcontainer',
        'deps',
        'deps-dev',
      ],
    ],
  },
};
