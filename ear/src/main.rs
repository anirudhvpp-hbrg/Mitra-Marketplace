//! mitra-ear: records a meeting on this computer as two tracks.
//!
//!   mitra-ear devices                         JSON: the microphone and the output it would record
//!   mitra-ear who                             JSON: the programs recording from a microphone right now
//!   mitra-ear record --dir D [--segment 30] [--no-mic] [--no-system]
//!
//! `record` writes 16 kHz mono WAV pieces into D, one series per track:
//!   mic-0001.wav, mic-0002.wav ...   what you say (the default microphone)
//!   sys-0001.wav, sys-0002.wav ...   what the others say (whatever the computer is playing)
//! Two tracks, not one mix, so "who said it" starts from a fact: your own voice is on your own track.
//! A piece is written under a `.part` name and renamed when it is complete, so a reader never sees
//! half a file, and a crash loses at most the piece in hand. Both tracks follow the wall clock:
//! when the computer plays nothing, silence is written, so piece N of each track covers the same
//! half minute. `status.json` in D is rewritten every second. Recording ends when a file named
//! `stop` appears in D, when standard input closes, or when the process that started it is gone.
//!
//! It holds a few megabytes and no model. Nothing is sent anywhere.

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use serde_json::json;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use std::{env, fs, process, thread};

const RATE: u32 = 16_000;

/// Turns whatever a device delivers (any rate, any channel count) into 16 kHz mono samples.
struct Track {
    samples: Vec<i16>, // waiting to be written
    channels: usize,
    step: f64, // input frames per output sample
    pos: f64,  // where the next output sample falls, in input frames, relative to `last`
    last: f32, // the previous input frame (mono), for interpolation across callbacks
    peak: f32, // loudest sample since the last status
}

impl Track {
    fn new(in_rate: u32, channels: usize) -> Self {
        Track { samples: Vec::new(), channels: channels.max(1), step: in_rate as f64 / RATE as f64, pos: 0.0, last: 0.0, peak: 0.0 }
    }

    fn push(&mut self, data: &[f32]) {
        let ch = self.channels;
        let frames = data.len() / ch;
        let mono = |i: usize| -> f32 { data[i * ch..i * ch + ch].iter().sum::<f32>() / ch as f32 };
        if frames == 0 {
            return;
        }
        // Frame -1 is the last frame of the block before (`last`); frames 0.. are this block. Each
        // output sample lies at `pos` on that scale and is read off the line between its neighbours.
        let last = self.last;
        let at = |i: isize| -> f32 { if i < 0 { last } else { mono(i as usize) } };
        while self.pos < frames as f64 - 1.0 {
            let i = self.pos.floor() as isize;
            let frac = (self.pos - i as f64) as f32;
            let v = at(i) + (at(i + 1) - at(i)) * frac;
            self.peak = self.peak.max(v.abs());
            self.samples.push((v.clamp(-1.0, 1.0) * 32767.0) as i16);
            self.pos += self.step;
        }
        self.pos -= frames as f64;
        self.last = mono(frames - 1);
    }
}

struct Wav {
    file: fs::File,
    part: PathBuf,
    done: PathBuf,
    samples: u32,
}

impl Wav {
    fn create(dir: &Path, name: &str, n: u32) -> std::io::Result<Wav> {
        let done = dir.join(format!("{name}-{n:04}.wav"));
        let part = dir.join(format!("{name}-{n:04}.wav.part"));
        let mut file = fs::File::create(&part)?;
        file.write_all(&header(0))?;
        Ok(Wav { file, part, done, samples: 0 })
    }

    fn write(&mut self, s: &[i16]) -> std::io::Result<()> {
        let mut bytes = Vec::with_capacity(s.len() * 2);
        for v in s {
            bytes.extend_from_slice(&v.to_le_bytes());
        }
        self.samples += s.len() as u32;
        self.file.write_all(&bytes)
    }

    fn close(mut self) -> std::io::Result<()> {
        self.file.seek(SeekFrom::Start(0))?;
        self.file.write_all(&header(self.samples))?;
        self.file.flush()?;
        drop(self.file);
        fs::rename(&self.part, &self.done)
    }
}

fn header(samples: u32) -> [u8; 44] {
    let data = samples * 2;
    let mut h = [0u8; 44];
    h[0..4].copy_from_slice(b"RIFF");
    h[4..8].copy_from_slice(&(36 + data).to_le_bytes());
    h[8..16].copy_from_slice(b"WAVEfmt ");
    h[16..20].copy_from_slice(&16u32.to_le_bytes());
    h[20..22].copy_from_slice(&1u16.to_le_bytes()); // PCM
    h[22..24].copy_from_slice(&1u16.to_le_bytes()); // mono
    h[24..28].copy_from_slice(&RATE.to_le_bytes());
    h[28..32].copy_from_slice(&(RATE * 2).to_le_bytes());
    h[32..34].copy_from_slice(&2u16.to_le_bytes());
    h[34..36].copy_from_slice(&16u16.to_le_bytes());
    h[36..40].copy_from_slice(b"data");
    h[40..44].copy_from_slice(&data.to_le_bytes());
    h
}

/// Open a device for capture. For an output device this is a loopback: what it is playing.
fn listen(device: &cpal::Device, config: cpal::SupportedStreamConfig, track: Arc<Mutex<Track>>) -> Result<cpal::Stream, String> {
    let err = |e| eprintln!("[ear] stream error: {e}");
    let cfg = config.config();
    let stream = match config.sample_format() {
        cpal::SampleFormat::F32 => device.build_input_stream(&cfg, move |d: &[f32], _: &_| track.lock().unwrap().push(d), err, None),
        cpal::SampleFormat::I16 => device.build_input_stream(
            &cfg,
            move |d: &[i16], _: &_| {
                let f: Vec<f32> = d.iter().map(|v| *v as f32 / 32768.0).collect();
                track.lock().unwrap().push(&f)
            },
            err,
            None,
        ),
        cpal::SampleFormat::U16 => device.build_input_stream(
            &cfg,
            move |d: &[u16], _: &_| {
                let f: Vec<f32> = d.iter().map(|v| (*v as f32 - 32768.0) / 32768.0).collect();
                track.lock().unwrap().push(&f)
            },
            err,
            None,
        ),
        other => return Err(format!("sample format {other:?} is not handled")),
    }
    .map_err(|e| e.to_string())?;
    stream.play().map_err(|e| e.to_string())?;
    Ok(stream)
}

fn now_ms() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as u64).unwrap_or(0)
}

fn devices() {
    let host = cpal::default_host();
    let name = |d: Option<cpal::Device>| d.and_then(|d| d.name().ok());
    println!("{}", json!({"microphone": name(host.default_input_device()), "system": name(host.default_output_device()), "host": host.id().name()}));
}

struct Source {
    name: &'static str,
    track: Arc<Mutex<Track>>,
    wav: Option<Wav>,
    written: u64, // samples written over the whole recording
    device: String,
    _stream: cpal::Stream,
}

fn record(dir: PathBuf, segment_s: u64, want_mic: bool, want_sys: bool) -> Result<(), String> {
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let _ = fs::remove_file(dir.join("stop"));
    let host = cpal::default_host();
    let mut sources: Vec<Source> = vec![];
    let mut problems: Vec<String> = vec![];
    let mut open = |name: &'static str, dev: Option<cpal::Device>, loopback: bool| {
        let Some(dev) = dev else {
            problems.push(format!("{name}: no device"));
            return;
        };
        let label = dev.name().unwrap_or_else(|_| "unknown".into());
        let cfg = if loopback { dev.default_output_config() } else { dev.default_input_config() };
        match cfg.map_err(|e| e.to_string()).and_then(|c| {
            let track = Arc::new(Mutex::new(Track::new(c.sample_rate().0, c.channels() as usize)));
            listen(&dev, c, track.clone()).map(|s| (track, s))
        }) {
            Ok((track, stream)) => sources.push(Source { name, track, wav: None, written: 0, device: label, _stream: stream }),
            Err(e) => problems.push(format!("{name} ({label}): {e}")),
        }
    };
    if want_mic {
        open("mic", host.default_input_device(), false);
    }
    if want_sys {
        open("sys", host.default_output_device(), true);
    }
    if sources.is_empty() {
        return Err(format!("nothing could be recorded: {}", problems.join("; ")));
    }

    // Whoever started us: when they close our input, or are gone, the recording ends cleanly.
    let ended = Arc::new(AtomicBool::new(false));
    {
        let flag = ended.clone();
        thread::spawn(move || {
            let mut buf = [0u8; 64];
            let mut stdin = std::io::stdin();
            while matches!(stdin.read(&mut buf), Ok(n) if n > 0) {}
            flag.store(true, Ordering::SeqCst);
        });
    }

    let started = Instant::now();
    let started_ms = now_ms();
    let per_segment = segment_s * RATE as u64;
    let mut segment: u32 = 1;
    let mut last_status = Instant::now() - Duration::from_secs(5);
    let mut levels: Vec<f32> = vec![0.0; sources.len()];
    loop {
        let stop = dir.join("stop").exists() || ended.load(Ordering::SeqCst);
        // every track is held to the wall clock, so piece N covers the same half minute on each
        let due = (started.elapsed().as_secs_f64() * RATE as f64) as u64;
        let seg_end = segment as u64 * per_segment;
        let mut all_reached = true;
        for (i, s) in sources.iter_mut().enumerate() {
            let mut fresh: Vec<i16> = {
                let mut t = s.track.lock().unwrap();
                levels[i] = levels[i].max(t.peak);
                t.peak = 0.0;
                std::mem::take(&mut t.samples)
            };
            let have = s.written + fresh.len() as u64;
            if have + RATE as u64 / 2 < due {
                fresh.resize(fresh.len() + (due - have) as usize, 0); // nothing was playing: silence keeps the clock
            }
            let room = seg_end.saturating_sub(s.written) as usize;
            let (now, later) = if fresh.len() > room { fresh.split_at(room) } else { (&fresh[..], &[][..]) };
            if s.wav.is_none() && (!now.is_empty() || !stop) {
                s.wav = Some(Wav::create(&dir, s.name, segment).map_err(|e| e.to_string())?);
            }
            if let Some(w) = s.wav.as_mut() {
                w.write(now).map_err(|e| e.to_string())?;
            }
            s.written += now.len() as u64;
            if !later.is_empty() {
                s.track.lock().unwrap().samples.splice(0..0, later.iter().copied()); // belongs to the next piece
            }
            if s.written < seg_end {
                all_reached = false;
            }
        }
        if all_reached || stop {
            for s in sources.iter_mut() {
                if let Some(w) = s.wav.take() {
                    if w.samples > 0 {
                        w.close().map_err(|e| e.to_string())?;
                    } else {
                        let _ = fs::remove_file(&w.part);
                    }
                }
            }
            if !stop {
                segment += 1;
            }
        }
        if last_status.elapsed() >= Duration::from_secs(1) || stop {
            let st = json!({
                "pid": process::id(), "state": if stop { "ended" } else { "recording" }, "started_ms": started_ms,
                "seconds": started.elapsed().as_secs(), "segment_s": segment_s,
                "pieces_done": if stop { segment } else { segment - 1 },
                "tracks": sources.iter().enumerate().map(|(i, s)| json!({"name": s.name, "device": s.device, "level": (levels[i] * 100.0).round() / 100.0})).collect::<Vec<_>>(),
                "problems": problems,
            });
            let tmp = dir.join("status.tmp");
            if fs::write(&tmp, st.to_string()).is_ok() {
                let _ = fs::rename(&tmp, dir.join("status.json"));
            }
            levels.iter_mut().for_each(|l| *l = 0.0);
            last_status = Instant::now();
        }
        if stop {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(200));
    }
}

/// The programs recording from a microphone right now, as Windows' own audio sessions report them.
/// This is how a meeting is noticed: a call app has an active capture session. Nothing is listened to.
#[cfg(windows)]
fn who() -> Vec<serde_json::Value> {
    use windows::core::Interface;
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::Media::Audio::{
        eCapture, AudioSessionStateActive, IAudioSessionControl2, IAudioSessionManager2, IMMDeviceEnumerator, MMDeviceEnumerator, DEVICE_STATE_ACTIVE,
    };
    use windows::Win32::System::Com::{CoCreateInstance, CoInitializeEx, CLSCTX_ALL, COINIT_MULTITHREADED};
    use windows::Win32::System::Threading::{OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION};
    let mut out = vec![];
    let mut seen: Vec<u32> = vec![];
    unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        let Ok(en) = CoCreateInstance::<_, IMMDeviceEnumerator>(&MMDeviceEnumerator, None, CLSCTX_ALL) else { return out };
        let Ok(devices) = en.EnumAudioEndpoints(eCapture, DEVICE_STATE_ACTIVE) else { return out };
        for i in 0..devices.GetCount().unwrap_or(0) {
            let Ok(dev) = devices.Item(i) else { continue };
            let Ok(mgr) = dev.Activate::<IAudioSessionManager2>(CLSCTX_ALL, None) else { continue };
            let Ok(sessions) = mgr.GetSessionEnumerator() else { continue };
            for j in 0..sessions.GetCount().unwrap_or(0) {
                let Ok(c) = sessions.GetSession(j) else { continue };
                if c.GetState().map_or(true, |s| s != AudioSessionStateActive) {
                    continue;
                }
                let Ok(c2) = c.cast::<IAudioSessionControl2>() else { continue };
                let pid = c2.GetProcessId().unwrap_or(0);
                if pid == 0 || pid == process::id() || seen.contains(&pid) {
                    continue;
                }
                seen.push(pid);
                let mut name = String::new();
                if let Ok(h) = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) {
                    let mut buf = [0u16; 1024];
                    let mut len = buf.len() as u32;
                    if QueryFullProcessImageNameW(h, PROCESS_NAME_WIN32, windows::core::PWSTR(buf.as_mut_ptr()), &mut len).is_ok() {
                        let full = String::from_utf16_lossy(&buf[..len as usize]);
                        name = full.rsplit(|c| c == '/' || c == 92 as char).next().unwrap_or("").to_string();
                    }
                    let _ = CloseHandle(h);
                }
                out.push(json!({"pid": pid, "name": name}));
            }
        }
    }
    out
}

#[cfg(not(windows))]
fn who() -> Vec<serde_json::Value> {
    vec![]
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("devices") => devices(),
        Some("who") => println!("{}", json!({"using": who()})),
        Some("record") => {
            let (mut dir, mut segment, mut mic, mut sys) = (None, 30u64, true, true);
            let mut it = args[1..].iter();
            while let Some(a) = it.next() {
                match a.as_str() {
                    "--dir" => dir = it.next().map(PathBuf::from),
                    "--segment" => segment = it.next().and_then(|v| v.parse().ok()).unwrap_or(30).clamp(5, 600),
                    "--no-mic" => mic = false,
                    "--no-system" => sys = false,
                    other => {
                        eprintln!("[ear] unknown argument {other}");
                        process::exit(2);
                    }
                }
            }
            let Some(dir) = dir else {
                eprintln!("[ear] --dir is required");
                process::exit(2);
            };
            if let Err(e) = record(dir, segment, mic, sys) {
                eprintln!("[ear] {e}");
                process::exit(1);
            }
        }
        _ => {
            eprintln!("usage: mitra-ear devices\n       mitra-ear record --dir D [--segment 30] [--no-mic] [--no-system]");
            process::exit(2);
        }
    }
}
