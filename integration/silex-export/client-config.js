// SPDX-License-Identifier: GPL-3.0-only
export default async function (config) {
  // Fixture exercises portable static export; CMS/11ty and remote fonts are not
  // selected. Normal editor, pages, text/style controls and preview stay intact.
  config.cmsConfig = { ...config.cmsConfig, enabled: false };
  // The pinned fonts plugin throws synchronously on an empty api_key during
  // editor creation. This is a synthetic token, never a service credential;
  // both service URLs stay loopback-only and this fixture selects system fonts.
  config.fontsApiKey = 'VOLPAROSSA_SYNTHETIC_OFFLINE_FONT_TOKEN';
  config.fontsServerUrl = 'http://127.0.0.1:6805/disabled-fonts';
  config.fontsApiUrl = 'http://127.0.0.1:6805/disabled-fonts';
  return {};
}
