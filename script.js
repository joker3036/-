// 설문 상태 관리
const surveyState = {
  currentQuestion: 1,
  answers: {
    q1: null,
    q2: null,
    q3: null,
    q4: null,
    q5: null,
  },
  userName: '',
  userPhone: '',
};

const totalQuestions = 6;

// 모바일 메뉴
const menuBtn = document.getElementById('menuBtn');
const mobileMenu = document.getElementById('mobileMenu');

menuBtn?.addEventListener('click', () => {
  mobileMenu.classList.toggle('active');
});

// 설문 네비게이션
const nextBtn = document.getElementById('nextBtn');
const prevBtn = document.getElementById('prevBtn');

nextBtn?.addEventListener('click', handleNext);
prevBtn?.addEventListener('click', handlePrev);

function handleNext() {
  // Q6 (정보입력) 특수 처리
  if (surveyState.currentQuestion === 6) {
    const userName = document.getElementById('userName').value.trim();
    if (!userName) {
      alert('성함을 입력해주세요');
      return;
    }
    surveyState.userName = userName;
    surveyState.userPhone = document.getElementById('userPhone').value.trim();
    showResults();
    return;
  }

  // Q1~Q5 설문 체크
  if (!surveyState.answers[`q${surveyState.currentQuestion}`]) {
    alert('선택지를 선택해주세요');
    return;
  }

  goToQuestion(surveyState.currentQuestion + 1);
}

function handlePrev() {
  if (surveyState.currentQuestion > 1) {
    goToQuestion(surveyState.currentQuestion - 1);
  }
}

function goToQuestion(questionNum) {
  const currentQ = document.getElementById(`q${surveyState.currentQuestion}`);
  const nextQ = document.getElementById(`q${questionNum}`);

  if (currentQ) currentQ.classList.remove('active');
  if (nextQ) nextQ.classList.add('active');

  surveyState.currentQuestion = questionNum;
  updateProgressBar();
  updateNavButtons();

  // 선택지 활성화 상태 복원
  restoreSelectedOption(questionNum);
}

function updateProgressBar() {
  const progress = (surveyState.currentQuestion / totalQuestions) * 100;
  document.getElementById('progressBar').style.width = progress + '%';
  document.getElementById('progressText').textContent = `${surveyState.currentQuestion}/${totalQuestions}`;
}

function updateNavButtons() {
  if (surveyState.currentQuestion === 1) {
    prevBtn.style.display = 'none';
  } else {
    prevBtn.style.display = 'block';
  }

  if (surveyState.currentQuestion === totalQuestions) {
    nextBtn.textContent = '결과 보기';
  } else {
    nextBtn.textContent = '다음';
  }
}

// 선택지 클릭 이벤트
document.querySelectorAll('.survey-option').forEach((button) => {
  button.addEventListener('click', handleOptionClick);
});

function handleOptionClick(e) {
  const button = e.currentTarget;
  const parent = button.parentElement;

  // 같은 그룹 내 다른 버튼 선택 해제
  parent.querySelectorAll('.survey-option').forEach((btn) => {
    btn.classList.remove('selected');
  });

  // 현재 버튼 선택
  button.classList.add('selected');

  // 답변 저장
  const questionNum = surveyState.currentQuestion;
  const answerValue = button.getAttribute('data-answer');
  surveyState.answers[`q${questionNum}`] = answerValue;
}

function restoreSelectedOption(questionNum) {
  const answeredValue = surveyState.answers[`q${questionNum}`];
  if (!answeredValue) return;

  const questionDiv = document.getElementById(`q${questionNum}`);
  questionDiv.querySelectorAll('.survey-option').forEach((btn) => {
    btn.classList.remove('selected');
    if (btn.getAttribute('data-answer') === answeredValue) {
      btn.classList.add('selected');
    }
  });
}

// 결과 계산 및 표시
function showResults() {
  const riskScore = calculateRiskScore();
  const comments = generateComments();

  // 위험도 표시
  const riskLevelText = getRiskLevelText(riskScore);
  const riskDescription = getRiskDescription(riskScore);

  document.getElementById('riskLevel').textContent = riskLevelText;
  document.getElementById('riskDescription').textContent = riskDescription;

  // 맞춤 코멘트 표시
  const commentsContainer = document.getElementById('resultComments');
  commentsContainer.innerHTML = comments
    .map((comment) => `<div class="result-item">${comment}</div>`)
    .join('');

  // 섹션 전환
  document.getElementById('surveyContainer').style.display = 'none';
  document.getElementById('resultsSection').classList.remove('hidden');

  // 스크롤 위치 조정
  document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });
}

function calculateRiskScore() {
  let score = 0;

  // Q1: 고민한 정도
  if (surveyState.answers.q1 === 'yes') score += 2;
  else if (surveyState.answers.q1 === 'unsure') score += 1;

  // Q2: 월납 보험료
  if (surveyState.answers.q2 === '40-plus') score += 3;
  else if (surveyState.answers.q2 === '30-40') score += 2;
  else if (surveyState.answers.q2 === 'unknown') score += 2;
  else if (surveyState.answers.q2 === '20-30') score += 1;

  // Q3: 보장 구성 인지도
  if (surveyState.answers.q3 === 'none') score += 3;
  else if (surveyState.answers.q3 === 'partial') score += 1;

  // Q4: 보험 관리 경험
  if (surveyState.answers.q4 === 'no') score += 2;

  // Q5: 보험사 지인 유무
  if (surveyState.answers.q5 === 'yes') score += 1;

  return Math.min(score, 10);
}

function getRiskLevelText(score) {
  if (score >= 7) return '⚠️ 높음 - 즉시 확인 필요';
  if (score >= 4) return '📊 보통 - 점검 권장';
  return '✅ 낮음 - 잘 관리 중';
}

function getRiskDescription(score) {
  if (score >= 7)
    return '당신의 보장분석은 매우 중요합니다. 무료 상담으로 정확히 진단해드리겠습니다.';
  if (score >= 4)
    return '일부 보장 공백이나 비효율이 있을 수 있습니다. 전문가 상담을 받아보세요.';
  return '현재 보험 상태가 비교적 양호하나, 정기적인 점검은 필수입니다.';
}

function generateComments() {
  const comments = [];

  // Q1 코멘트
  if (surveyState.answers.q1 === 'yes') {
    comments.push('실제로 많은 분들이 막상 분석을 받아보면 몰랐던 보장 공백을 발견합니다.');
  }

  // Q2 코멘트
  if (surveyState.answers.q2 === '40-plus' || surveyState.answers.q2 === 'unknown') {
    comments.push(
      '월 보험료가 높거나 파악이 안 되고 있다면, 중복·비효율 설계로 새는 돈이 있을 가능성이 큽니다.'
    );
  }

  // Q3 코멘트
  if (surveyState.answers.q3 === 'none') {
    comments.push('본인의 보장 구성을 모른다면, 정작 필요한 순간 보장이 안 될 위험이 있습니다.');
  }

  // Q4 코멘트
  if (surveyState.answers.q4 === 'no') {
    comments.push('1년 이상 보험 관리를 받지 않으셨다면, 청구 가능한데 놓친 보험금이 있을 수 있습니다.');
  }

  // Q5 코멘트
  if (surveyState.answers.q5 === 'yes') {
    comments.push(
      '지인을 통해 가입하신 경우, 여러 보험사 비교 없이 한 곳 상품 위주로 설계됐을 가능성이 있습니다.'
    );
  } else if (surveyState.answers.q5 === 'no') {
    comments.push('객관적으로 비교해줄 사람이 없었다면, 가입 당시 설계가 그대로 방치됐을 가능성이 높습니다.');
  }

  // 최소 1개 코멘트는 있어야 함
  if (comments.length === 0) {
    comments.push('정기적인 보장분석을 통해 최적의 보험 상태를 유지하세요.');
  }

  return comments;
}

// 이메일 상담 신청
document.getElementById('emailBtn')?.addEventListener('click', () => {
  const subject = `보장분석 상담 신청 - ${surveyState.userName}`;

  const answers = `
Q1. 보장분석 고민: ${getAnswerText('q1')}
Q2. 월납 보험료: ${getAnswerText('q2')}
Q3. 보장 구성 인지: ${getAnswerText('q3')}
Q4. 보험 관리 경험: ${getAnswerText('q4')}
Q5. 보험사 지인: ${getAnswerText('q5')}

위험도: ${document.getElementById('riskLevel').textContent}
`;

  const body = encodeURIComponent(
    `안녕하세요, 조민우 설계사님\n\n보장분석 상담을 신청합니다.\n\n[고객 정보]\n성함: ${surveyState.userName}\n연락처: ${surveyState.userPhone || '기입 안 함'}\n\n[설문 결과]\n${answers}\n\n감사합니다.`
  );

  // ⚠️ 실제 이메일로 교체 필요: example@example.com → 실제 이메일 주소
  window.location.href = `mailto:example@example.com?subject=${encodeURIComponent(subject)}&body=${body}`;
});

// 다시 설문하기
document.getElementById('restartBtn')?.addEventListener('click', () => {
  surveyState.currentQuestion = 1;
  surveyState.answers = { q1: null, q2: null, q3: null, q4: null, q5: null };
  surveyState.userName = '';
  surveyState.userPhone = '';

  document.getElementById('userName').value = '';
  document.getElementById('userPhone').value = '';

  document.querySelectorAll('.survey-option').forEach((btn) => {
    btn.classList.remove('selected');
  });

  goToQuestion(1);

  document.getElementById('surveyContainer').style.display = 'block';
  document.getElementById('resultsSection').classList.add('hidden');
  document.getElementById('survey').scrollIntoView({ behavior: 'smooth' });
});

function getAnswerText(questionKey) {
  const answerMap = {
    // Q1
    yes: '그렇다',
    no: '아니다',
    unsure: '잘 모르겠다',
    // Q2
    '10-20': '10만원대',
    '20-30': '20만원대',
    '30-40': '30만원대',
    '40-plus': '40만원 이상',
    unknown: '모름',
    // Q3
    well: '정확히 안다',
    partial: '대략은 안다',
    none: '전혀 모른다',
  };

  return answerMap[surveyState.answers[questionKey]] || '선택 안 함';
}

// 초기 설정
updateProgressBar();
updateNavButtons();
