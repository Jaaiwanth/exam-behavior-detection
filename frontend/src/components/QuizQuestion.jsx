// src/components/QuizQuestion.jsx
import React from "react";

export default function QuizQuestion({ question, qIndex, total, selectedIndex, onSelect, submitted }) {
  if (!question) return null;
  const letters = ["A", "B", "C", "D"];

  return (
    <div className="exam-question-card">
      <div className="exam-question-header">
        <span className="exam-question-meta">
          Question {qIndex + 1} of {total}
        </span>
      </div>

      <p className="exam-question-text">
        {question.question}
      </p>

      <div className="exam-options-list">
        {question.options.map((opt, i) => {
          const isSelected = selectedIndex === i;
          return (
            <button
              key={i}
              disabled={submitted}
              onClick={() => onSelect(i)}
              className={`exam-option-btn ${isSelected ? "selected" : ""}`}
            >
              <span className={`exam-option-letter ${isSelected ? "selected" : ""}`}>
                {letters[i]}
              </span>
              <span className="exam-option-content">{opt}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
