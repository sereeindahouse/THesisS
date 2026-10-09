"""Record a short microphone sample. This does not perform recognition."""
import argparse
from pathlib import Path

def main():
    import sounddevice as sd
    from scipy.io.wavfile import write
    p = argparse.ArgumentParser()
    p.add_argument('--output', default='audio/q01.wav')
    p.add_argument('--seconds', type=float, default=8)
    p.add_argument('--device', type=int)
    p.add_argument('--list-devices', action='store_true')
    a = p.parse_args()
    if a.list_devices:
        print(sd.query_devices())
        return
    if not 1 <= a.seconds <= 60:
        p.error('--seconds must be between 1 and 60')
    destination = Path(a.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        p.error('Output already exists. Choose a new filename to preserve the recording.')
    device_info = sd.query_devices(a.device, 'input')
    # Use the microphone's native sample rate; the STT decoder resamples later.
    rate = int(device_info['default_samplerate'])
    input('Press Enter, then speak after RECORDING appears: ')
    print('RECORDING...', flush=True)
    audio = sd.rec(round(a.seconds * rate), samplerate=rate, channels=1,
                   dtype='int16', device=a.device)
    sd.wait()
    write(destination, rate, audio)
    print(f'Saved: {destination} ({rate} Hz, mono)')

if __name__ == '__main__':
    main()
