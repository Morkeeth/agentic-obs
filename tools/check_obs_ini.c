/* Parser-only test utility. Never calls obs_startup or loads capture plugins. */
#include <stdio.h>
#include <string.h>
#include <util/config-file.h>
#include <obs-data.h>
int main(int argc, char **argv)
{
    if (argc == 3 && !strcmp(argv[1], "--scene")) {
        obs_data_t *data = obs_data_create_from_json_file(argv[2]);
        if (!data) return 2;
        int status = strcmp(obs_data_get_string(data, "name"), "Expanded Director") ? 3 : 0;
        const char *slots[] = {"DesktopAudioDevice1", "DesktopAudioDevice2", "AuxAudioDevice1",
                               "AuxAudioDevice2", "AuxAudioDevice3", "AuxAudioDevice4"};
        for (int i = 0; i < 6; ++i) {
            obs_data_t *audio = obs_data_get_obj(data, slots[i]);
            if (audio) { status = 3; obs_data_release(audio); }
        }
        obs_data_array_t *sources = obs_data_get_array(data, "sources");
        if (!sources || obs_data_array_count(sources) != 1) status = 3;
        if (sources && obs_data_array_count(sources) == 1) {
            obs_data_t *source = obs_data_array_item(sources, 0);
            if (strcmp(obs_data_get_string(source, "id"), "scene")) status = 3;
            obs_data_t *settings = obs_data_get_obj(source, "settings");
            obs_data_array_t *items = settings ? obs_data_get_array(settings, "items") : NULL;
            if (!items || obs_data_array_count(items) != 0) status = 3;
            if (items) obs_data_array_release(items);
            if (settings) obs_data_release(settings);
            obs_data_release(source);
        }
        if (sources) obs_data_array_release(sources);
        obs_data_release(data);
        return status;
    }
    if (argc < 5 || (argc - 2) % 3) return 2;
    config_t *config = NULL;
    if (config_open(&config, argv[1], CONFIG_OPEN_EXISTING) != CONFIG_SUCCESS) return 2;
    int status = 0;
    for (int i = 2; i < argc; i += 3) {
        const char *value = config_get_string(config, argv[i], argv[i + 1]);
        if (!value || strcmp(value, argv[i + 2])) {
            fprintf(stderr, "OBS fixture key mismatch: %s.%s\n", argv[i], argv[i + 1]);
            status = 3;
        }
    }
    config_close(config);
    return status;
}
