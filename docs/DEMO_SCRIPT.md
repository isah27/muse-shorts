# muse-shorts demo voiceover (Isah narrates)

About 2 minutes. Draft video: `outputs/demo/demo_draft.mp4` (1080x1920, 2:07). Each segment's slot below matches the draft timeline; slots with no clip audio are silent so you can drop your recording in. On the clip segments, the Short's own audio is turned down to 25% so your voice sits on top.

| # | Time | On screen | Voiceover |
|---|------|-----------|-----------|
| 1 | 0:00–0:15 (15 s) | English vaccines Short playing, label "English · sourced + fact-checked" | "Hi, I'm Isah, a developer and content creator in Lagos. This Short explains how vaccines train the immune system. Every sentence in it is backed by a real source, and an AI agent made it in a few minutes." |
| 2 | 0:15–0:30 (15 s) | Card: "The problem" | "Here in Nigeria, false health information spreads faster than the truth. Most good science content is in English, but millions of us learn best in Pidgin, Yoruba, Hausa or Igbo. So the gap gets filled by rumours." |
| 3 | 0:30–0:45 (15 s) | Card: the pipeline, topic in to human approval | "muse-shorts fixes that. You type a topic. The agent pulls sources from Wikipedia and PubMed, writes a script where every claim quotes its source, checks every claim, makes the pictures, translates, voices and captions it, then waits for me to approve it." |
| 4 | 0:45–1:05 (20 s) | App screenshots: live agent timeline, claim critic, SAM gate, labeled frames | "This is the agent working live. It isn't a fixed script. Meta's Muse Spark Open model picks each tool, one step at a time. Watch the red cards: the critic caught lines the sources didn't support and sent them back to be rewritten. Then Muse Image draws each frame, and SAM 3.1 has to find every labeled part, or the label is dropped." |
| 5 | 1:05–1:20 (15 s) | Card: "Verification trace" | "Every run ends with a trace. For this health topic, the rule is strict: one hundred percent of claims verified. In round one, five lines were rejected. In round two, everything passed. Captions match the voice, files are fingerprinted, and nothing goes out until a human approves it." |
| 6 | 1:20–1:40 (20 s) | Pidgin, Yoruba, Hausa, Igbo clips, 5 s each, language label on top | "And here's the part I care about most. The same verified Short in Nigerian Pidgin, in Yoruba, in Hausa and in Igbo. Each translation is translated back into English and checked, so the meaning can't drift. The voice is WazobiaVoice, an open-weights Nigerian voice model. I checked every one by ear, and so did my friends." |
| 7 | 1:40–1:55 (15 s) | Card: "Built on Meta" | "Under the hood: Muse Spark Open, Meta's open-weights model on Baseten, runs the agent and the critic. Muse Image and SAM 3.1 make and check the pictures. The voices are rendered on Kaggle GPUs, and gates at every stage block the agent from skipping a check." |
| 8 | 1:55–2:07 (12 s) | Card: "Shorts you can trust" | "muse-shorts: Shorts you can trust. Sourced, verified, and in your own language. Thank you." |

Recording tips: record each segment as its own file, keep it a little under its time slot, and name the files seg1.wav to seg8.wav so they can be laid onto the timeline.
