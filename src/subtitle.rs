use std::collections::{HashMap, VecDeque};

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct SubtitleSegment {
    pub id: u64,
    pub revision: u64,
    pub start_time_ms: u64,
    pub end_time_ms: u64,
    pub original_text: Option<String>,
    pub translated_text: String,
    pub display_lines: Vec<String>,
    pub source_language: String,
    pub language_confidence: f32,
    pub is_partial: bool,
    pub is_final: bool,
    pub confidence: Option<f32>,
    pub asr_latency_ms: Option<u64>,
    pub end_to_end_latency_ms: Option<u64>,
}

#[derive(Clone, Debug)]
pub struct TranscriptHypothesis {
    pub segment_id: u64,
    pub revision: u64,
    pub text: String,
    pub source_text: Option<String>,
    pub source_language: String,
    pub language_confidence: f32,
    pub is_final: bool,
    pub audio_start_ms: u64,
    pub audio_end_ms: u64,
    pub asr_started_ms: Option<u64>,
    pub asr_completed_ms: Option<u64>,
    pub confidence: Option<f32>,
    pub suppressed: bool,
    pub end_to_end_latency_ms: Option<u64>,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum SubtitleUpdate {
    Upsert { segment: SubtitleSegment },
    Clear { segment_id: u64 },
}

#[derive(Debug)]
pub struct SubtitleAssembler {
    current: Option<SubtitleSegment>,
    history: VecDeque<SubtitleSegment>,
    recent_final_text: String,
    max_history: usize,
    max_line_chars: usize,
    max_lines: usize,
    language: LanguageTracker,
}

impl Default for SubtitleAssembler {
    fn default() -> Self {
        Self {
            current: None,
            history: VecDeque::new(),
            recent_final_text: String::new(),
            max_history: 500,
            max_line_chars: 44,
            max_lines: 2,
            language: LanguageTracker::default(),
        }
    }
}

impl SubtitleAssembler {
    pub fn with_layout(max_line_chars: usize, max_lines: usize) -> Self {
        Self {
            max_line_chars: max_line_chars.max(12),
            max_lines: max_lines.clamp(1, 3),
            ..Self::default()
        }
    }

    pub fn current(&self) -> Option<&SubtitleSegment> {
        self.current.as_ref()
    }

    pub fn history(&self) -> &VecDeque<SubtitleSegment> {
        &self.history
    }

    pub fn detected_language(&self) -> Option<(&str, f32)> {
        self.language.current()
    }

    pub fn apply(&mut self, hypothesis: TranscriptHypothesis) -> Option<SubtitleUpdate> {
        if hypothesis.suppressed {
            if hypothesis.is_final
                && self.current.as_ref().map(|item| item.id) == Some(hypothesis.segment_id)
            {
                self.current = None;
                return Some(SubtitleUpdate::Clear {
                    segment_id: hypothesis.segment_id,
                });
            }
            return None;
        }
        let mut text = normalize_text(&hypothesis.text);
        if text.is_empty() {
            return None;
        }

        if let Some(current) = self.current.as_ref()
            && (hypothesis.segment_id < current.id
                || (hypothesis.segment_id == current.id && hypothesis.revision <= current.revision))
        {
            return None;
        }

        // Whisper translations may rewrite the beginning of a rolling window.
        // Keep the already visible tentative phrase until final unless the new
        // partial is a recognizable extension/refinement. This avoids flashing
        // a wholly different sentence every partial interval.
        if !hypothesis.is_final
            && let Some(current) = self.current.as_ref()
            && current.id == hypothesis.segment_id
            && current.is_partial
            && (current.translated_text == text
                || !is_stable_partial_revision(&current.translated_text, &text))
        {
            return None;
        }

        if self.current.as_ref().map(|item| item.id) != Some(hypothesis.segment_id) {
            text = remove_cross_segment_overlap(&self.recent_final_text, &text);
            if text.is_empty() {
                return None;
            }
        }

        self.language.update(
            hypothesis.source_language.clone(),
            hypothesis.language_confidence,
        );
        let segment = SubtitleSegment {
            id: hypothesis.segment_id,
            revision: hypothesis.revision,
            start_time_ms: hypothesis.audio_start_ms,
            end_time_ms: hypothesis.audio_end_ms,
            original_text: hypothesis
                .source_text
                .as_deref()
                .map(normalize_text)
                .filter(|value| !value.is_empty()),
            display_lines: layout_lines(&text, self.max_line_chars, self.max_lines),
            translated_text: text.clone(),
            source_language: hypothesis.source_language,
            language_confidence: hypothesis.language_confidence.clamp(0.0, 1.0),
            is_partial: !hypothesis.is_final,
            is_final: hypothesis.is_final,
            confidence: hypothesis.confidence,
            asr_latency_ms: hypothesis
                .asr_started_ms
                .zip(hypothesis.asr_completed_ms)
                .map(|(start, end)| end.saturating_sub(start)),
            end_to_end_latency_ms: hypothesis.end_to_end_latency_ms,
        };
        self.current = Some(segment.clone());

        if hypothesis.is_final {
            self.recent_final_text = append_bounded(&self.recent_final_text, &text, 80);
            self.history.push_back(segment.clone());
            while self.history.len() > self.max_history {
                self.history.pop_front();
            }
        }
        Some(SubtitleUpdate::Upsert { segment })
    }

    pub fn clear_stale(&mut self, stream_time_ms: u64, timeout_ms: u64) -> Option<SubtitleUpdate> {
        let current = self.current.as_ref()?;
        if stream_time_ms.saturating_sub(current.end_time_ms) < timeout_ms {
            return None;
        }
        let segment_id = current.id;
        self.current = None;
        Some(SubtitleUpdate::Clear { segment_id })
    }
}

#[derive(Debug, Default)]
struct LanguageTracker {
    scores: HashMap<String, f32>,
    current: Option<String>,
}

impl LanguageTracker {
    fn update(&mut self, language: String, confidence: f32) {
        if language.is_empty() || language == "unknown" || confidence < 0.30 {
            return;
        }
        for value in self.scores.values_mut() {
            *value *= 0.82;
        }
        *self.scores.entry(language.clone()).or_default() += confidence;
        let (best_language, best_score) = self
            .scores
            .iter()
            .max_by(|left, right| left.1.total_cmp(right.1))
            .map(|(key, value)| (key.clone(), *value))
            .expect("language score was just inserted");
        let current_score = self
            .current
            .as_ref()
            .and_then(|current| self.scores.get(current))
            .copied()
            .unwrap_or_default();
        if self.current.is_none()
            || self.current.as_deref() == Some(best_language.as_str())
            || best_score > current_score + 0.35
        {
            self.current = Some(best_language);
        }
    }

    fn current(&self) -> Option<(&str, f32)> {
        let language = self.current.as_deref()?;
        let score = self.scores.get(language).copied().unwrap_or_default();
        Some((language, score.min(1.0)))
    }
}

fn normalize_text(input: &str) -> String {
    input.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn append_bounded(previous: &str, next: &str, max_words: usize) -> String {
    let words: Vec<&str> = previous
        .split_whitespace()
        .chain(next.split_whitespace())
        .collect();
    words[words.len().saturating_sub(max_words)..].join(" ")
}

fn comparable_word(word: &str) -> String {
    word.trim_matches(|character: char| !character.is_alphanumeric())
        .to_lowercase()
}

fn remove_cross_segment_overlap(previous: &str, next: &str) -> String {
    let previous_words: Vec<&str> = previous.split_whitespace().collect();
    let next_words: Vec<&str> = next.split_whitespace().collect();
    let maximum = previous_words.len().min(next_words.len()).min(16);
    for overlap in (3..=maximum).rev() {
        let previous_suffix = &previous_words[previous_words.len() - overlap..];
        let next_prefix = &next_words[..overlap];
        if previous_suffix
            .iter()
            .zip(next_prefix)
            .all(|(left, right)| comparable_word(left) == comparable_word(right))
        {
            return next_words[overlap..].join(" ");
        }
    }
    next.to_owned()
}

fn is_stable_partial_revision(previous: &str, next: &str) -> bool {
    let previous_words: Vec<String> = previous.split_whitespace().map(comparable_word).collect();
    let next_words: Vec<String> = next.split_whitespace().map(comparable_word).collect();
    if previous_words.is_empty() || next_words.is_empty() {
        return false;
    }
    let common_prefix = previous_words
        .iter()
        .zip(&next_words)
        .take_while(|(left, right)| left == right)
        .count();
    let required_prefix = if previous_words.len() <= 2 {
        1
    } else {
        (previous_words.len() / 2).clamp(2, 5)
    };
    common_prefix >= required_prefix
}

pub fn layout_lines(text: &str, max_chars: usize, max_lines: usize) -> Vec<String> {
    let words: Vec<&str> = text.split_whitespace().collect();
    if words.is_empty() {
        return Vec::new();
    }
    if max_lines == 1 {
        return vec![words.join(" ")];
    }

    let total_chars = words.iter().map(|word| word.chars().count()).sum::<usize>()
        + words.len().saturating_sub(1);
    if total_chars <= max_chars {
        return vec![words.join(" ")];
    }

    let mut best_split = None;
    let mut best_score = usize::MAX;
    for split in 1..words.len() {
        let left = words[..split].join(" ");
        let right = words[split..].join(" ");
        let left_len = left.chars().count();
        let right_len = right.chars().count();
        let overflow = left_len.saturating_sub(max_chars) + right_len.saturating_sub(max_chars);
        let punctuation_penalty =
            usize::from(!words[split - 1].ends_with([',', '.', '?', '!', ':', ';'])) * 24;
        let score = overflow * 100 + left_len.abs_diff(right_len) + punctuation_penalty;
        if score < best_score {
            best_score = score;
            best_split = Some(split);
        }
    }
    if let Some(split) = best_split {
        return vec![words[..split].join(" "), words[split..].join(" ")];
    }

    vec![words.join(" ")]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hypothesis(id: u64, revision: u64, text: &str, final_result: bool) -> TranscriptHypothesis {
        TranscriptHypothesis {
            segment_id: id,
            revision,
            text: text.to_owned(),
            source_text: Some("天気です".to_owned()),
            source_language: "ja".to_owned(),
            language_confidence: 0.97,
            is_final: final_result,
            audio_start_ms: 0,
            audio_end_ms: 1_000,
            asr_started_ms: Some(1_100),
            asr_completed_ms: Some(1_350),
            confidence: Some(0.8),
            suppressed: false,
            end_to_end_latency_ms: Some(350),
        }
    }

    #[test]
    fn partials_replace_one_segment_and_stale_revisions_are_ignored() {
        let mut assembler = SubtitleAssembler::default();
        assembler.apply(hypothesis(1, 1, "I didn't know", false));
        assert!(
            assembler
                .apply(hypothesis(1, 2, "I didn't know", false))
                .is_none()
        );
        assembler.apply(hypothesis(1, 3, "I didn't know you were coming", false));
        assert_eq!(
            assembler.current().unwrap().translated_text,
            "I didn't know you were coming"
        );
        assert!(
            assembler
                .apply(hypothesis(1, 2, "stale text", false))
                .is_none()
        );
        assert!(assembler.history().is_empty());
    }

    #[test]
    fn major_partial_rewrites_are_held_until_final() {
        let mut assembler = SubtitleAssembler::default();
        assembler.apply(hypothesis(1, 1, "what almost in two", false));
        assert!(
            assembler
                .apply(hypothesis(1, 2, "which is almost twice as much", false))
                .is_none()
        );
        assert_eq!(
            assembler.current().unwrap().translated_text,
            "what almost in two"
        );
        assembler.apply(hypothesis(1, 3, "that is almost twice as much.", true));
        assert_eq!(
            assembler.current().unwrap().translated_text,
            "that is almost twice as much."
        );
    }

    #[test]
    fn removes_cross_segment_whisper_overlap() {
        let mut assembler = SubtitleAssembler::default();
        assembler.apply(hypothesis(1, 1, "I didn't know you were coming", true));
        assembler.apply(hypothesis(2, 1, "you were coming here tonight.", true));
        assert_eq!(
            assembler.current().unwrap().translated_text,
            "here tonight."
        );
        assert_eq!(assembler.history().len(), 2);
    }

    #[test]
    fn semantic_punctuation_is_preferred_for_two_lines() {
        let lines = layout_lines(
            "I really wanted to go there, because I had not seen her for three years.",
            44,
            2,
        );
        assert_eq!(lines.len(), 2);
        assert!(lines[0].ends_with(','));
        assert!(lines.iter().all(|line| line.chars().count() <= 44));
    }

    #[test]
    fn overlong_layout_never_discards_meaning() {
        let text = "We have two enemies on the left side and I think one is upstairs, while another player is waiting outside the building.";
        let lines = layout_lines(text, 32, 2);

        assert_eq!(lines.len(), 2);
        assert_eq!(lines.join(" "), text);
    }

    #[test]
    fn language_tracker_can_adapt_after_multiple_confident_samples() {
        let mut tracker = LanguageTracker::default();
        tracker.update("en".into(), 0.95);
        assert_eq!(tracker.current().unwrap().0, "en");
        tracker.update("ja".into(), 0.98);
        tracker.update("ja".into(), 0.98);
        assert_eq!(tracker.current().unwrap().0, "ja");
    }
}
