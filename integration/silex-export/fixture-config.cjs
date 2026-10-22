// SPDX-License-Identifier: GPL-3.0-only
// Disposable test configuration, not a production hosting connector.
const { join, resolve, dirname } = require('node:path');

module.exports = async function (config) {
  const source = resolve(process.env.STUDIO_SILEX_SOURCE);
  const temporary = resolve(process.env.STUDIO_FIXTURE_TEMP);
  if (!temporary.startsWith(resolve(process.env.RUNNER_TEMP) + '/')) {
    throw new Error('Fixture storage must be inside the disposable runner temporary directory');
  }
  const { FsStorage } = require(join(source, 'dist/server/server/connectors/FsStorage.js'));
  const DownloadConnector = require(join(source, 'dist/server/server/plugins/DownloadConnector.js')).default;
  const StaticPlugin = require(join(source, 'dist/server/server/plugins/StaticPlugin.js')).default;
  // loadUserConfig precedes loadSilexConfig: prevent loading the SaaS dashboard,
  // onboarding and public connectors after this isolated user configuration.
  config.configFilePath = join(__dirname, 'empty-server-config.cjs');
  config.port = { host: '127.0.0.1', port: 6805 };
  config.setStorageConnectors([new FsStorage(config, { path: join(temporary, 'storage') })]);
  config.setHostingConnectors([new DownloadConnector(config)]);
  const packageRoot = (name) => dirname(require.resolve(name + '/package.json', { paths: [source] }));
  await config.addPlugin(StaticPlugin, { routes: [
    { route: '/', path: join(source, 'public') },
    { route: '/', path: join(source, 'dist/client') },
    { route: '/css/', path: join(packageRoot('@fortawesome/fontawesome-free'), 'css') },
    { route: '/webfonts/', path: join(packageRoot('@fortawesome/fontawesome-free'), 'webfonts') },
    { route: '/css/files/', path: join(packageRoot('@fontsource/ubuntu'), 'files') },
  ] });
  return {};
};
