-- Pixelbook Go: prefer internal speakers over HDMI, force S16LE/48kHz
table.insert(alsa_monitor.rules, {
  matches = {
    {
      { "node.name", "matches", "alsa_output.platform-avs_max98373*" },
    },
  },
  apply_properties = {
    ["priority.driver"]  = 2000,
    ["priority.session"] = 2000,
    ["audio.format"]     = "S16LE",
    ["audio.rate"]       = 48000,
    ["audio.channels"]   = 2,
    ["audio.position"]   = "FL,FR",
    ["node.description"] = "Built-in Speakers",
  },
})

-- Keep HDMI at lower priority so it never auto-selects over speakers
table.insert(alsa_monitor.rules, {
  matches = {
    {
      { "node.name", "matches", "alsa_output.platform-avs_hdaudio*" },
    },
  },
  apply_properties = {
    ["priority.driver"]  = 500,
    ["priority.session"] = 500,
    ["node.description"] = "HDMI / DisplayPort",
  },
})
