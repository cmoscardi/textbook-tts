from kittentts import KittenTTS
m = KittenTTS("KittenML/kitten-tts-micro-0.8")
import time
import numpy as np

with open('tara.md') as tara_f:
    tara_text = tara_f.readlines()


def silence(seconds, sr=24000):
    return np.zeros(int(seconds * sr), dtype=np.float32)

tstart = time.time()
results = []
for sentence in tara_text:
    t1 = time.time()
    # ['Bella', 'Jasper', 'Luna', 'Bruno', 'Rosie', 'Hugo', 'Kiki', 'Leo']
    parsed = sentence.replace("\n", ".")
    if len(parsed.strip()) > 1:
        audio = m.generate(parsed,
                           voice='Bruno' )
        results.append(audio)
    results.append(silence(.75))
    t2 = time.time()
    print("generation time:", t2-t1)
    print("run time:", audio.shape[0] / 24000)

audio = np.concatenate(results, axis=0)
tend = time.time()
print("full time:", tend - tstart)

# available_voices : ['Bella', 'Jasper', 'Luna', 'Bruno', 'Rosie', 'Hugo', 'Kiki', 'Leo']

# Save the audio
import soundfile as sf
sf.write('full_output.mp3', audio, 24000)

