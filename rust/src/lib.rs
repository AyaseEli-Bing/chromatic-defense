//! td_rust: 塔防游戏的 Rust 原生库
//! 职责：① 敌人 AI 决策（受减速影响时的速度调整）
//!      ② 音效合成（方波 beep，生成 WAV 文件）
//! 通过 cdylib 导出 C ABI，供 Python ctypes 调用。

use std::ffi::CStr;
use std::os::raw::{c_char, c_int, c_float};
use std::fs::File;
use std::io::{Write, BufWriter};

/// 敌人 AI 步进：根据当前状态计算本帧移动。
/// 返回移动后的 (x, y) 和是否到达终点。
/// 参数：
///   ex, ey   — 敌人当前坐标（浮点，网格单位）
///   tx, ty   — 当前路径目标节点坐标
///   base_spd — 基础速度（格/秒）
///   slow_factor — 减速系数（1.0=正常，0.5=半速），来自魔法塔
///   dt       — 帧间隔（秒）
/// 输出：out[0]=new_x, out[1]=new_y, out[2]=reached_target(0/1)
#[no_mangle]
pub extern "C" fn rr_enemy_step(
    ex: c_float, ey: c_float,
    tx: c_float, ty: c_float,
    base_spd: c_float, slow_factor: c_float,
    dt: c_float, out: *mut c_float,
) {
    if out.is_null() { return; }
    let spd = base_spd * slow_factor.max(0.1);
    let dx = tx - ex;
    let dy = ty - ey;
    let dist = (dx * dx + dy * dy).sqrt();
    let step = spd * dt;

    let (nx, ny, reached) = if dist <= step || dist < 0.001 {
        (tx, ty, 1)
    } else {
        (ex + dx / dist * step, ey + dy / dist * step, 0)
    };

    unsafe {
        *out = nx;
        *out.add(1) = ny;
        *out.add(2) = reached as c_float;
    }
}

/// 选择下一个路径目标节点（简单策略：朝终点方向选最近的未走节点）
/// path: 路径坐标数组 [x0,y0,x1,y1,...]，path_len: 节点数
/// cur_idx: 当前目标节点索引
/// 返回新的目标索引
#[no_mangle]
pub extern "C" fn rr_next_target(cur_idx: c_int, path_len: c_int) -> c_int {
    if cur_idx + 1 < path_len { cur_idx + 1 } else { path_len - 1 }
}

/// 合成方波 beep 音效并写入 WAV 文件。
/// freq: 频率(Hz), dur_ms: 时长(ms), path: 输出文件路径
/// 返回 0=成功, -1=失败
#[no_mangle]
pub extern "C" fn rr_beep_to_wav(freq: c_float, dur_ms: c_int, path: *const c_char) -> c_int {
    if path.is_null() || dur_ms <= 0 || freq <= 0.0 { return -1; }
    let path_str = match unsafe { CStr::from_ptr(path) }.to_str() {
        Ok(s) => s,
        Err(_) => return -1,
    };

    let sample_rate: u32 = 22050;
    let total_samples = (sample_rate as u64 * dur_ms as u64 / 1000) as u32;

    // 生成方波样本 + 简单包络（避免爆音）
    let mut samples: Vec<i16> = Vec::with_capacity(total_samples as usize);
    let attack = (sample_rate as f32 * 0.005) as u32; // 5ms attack
    let release = (sample_rate as f32 * 0.05) as u32; // 50ms release
    for i in 0..total_samples {
        let t = i as f32 / sample_rate as f32;
        let phase = (t * freq * 2.0 * std::f32::consts::PI).sin();
        let sample = if phase >= 0.0 { 1.0 } else { -1.0 }; // 方波
        // 包络
        let env = if i < attack {
            i as f32 / attack as f32
        } else if i >= total_samples.saturating_sub(release) {
            (total_samples - i) as f32 / release.max(1) as f32
        } else {
            1.0
        };
        samples.push((sample * env * 0.3 * i16::MAX as f32) as i16);
    }

    // 写 WAV
    let file = match File::create(path_str) {
        Ok(f) => f,
        Err(_) => return -1,
    };
    let mut w = BufWriter::new(file);
    let data_len = total_samples * 2; // 16bit mono
    let _ = w.write_all(b"RIFF");
    let _ = w.write_all(&(36 + data_len).to_le_bytes());
    let _ = w.write_all(b"WAVE");
    let _ = w.write_all(b"fmt ");
    let _ = w.write_all(&16u32.to_le_bytes());       // PCM
    let _ = w.write_all(&1u16.to_le_bytes());        // PCM format
    let _ = w.write_all(&1u16.to_le_bytes());        // mono
    let _ = w.write_all(&sample_rate.to_le_bytes());
    let _ = w.write_all(&(sample_rate * 2).to_le_bytes()); // byte rate
    let _ = w.write_all(&2u16.to_le_bytes());        // block align
    let _ = w.write_all(&16u16.to_le_bytes());       // bits per sample
    let _ = w.write_all(b"data");
    let _ = w.write_all(&data_len.to_le_bytes());
    for s in &samples {
        let _ = w.write_all(&s.to_le_bytes());
    }
    let _ = w.flush();
    0
}
