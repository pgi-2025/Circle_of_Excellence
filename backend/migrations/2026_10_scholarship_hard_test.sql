-- =====================================================================
-- Scholarship test upgrade: hard mixed question bank + anti-cheat columns
-- Run ONCE in the Supabase SQL editor (safe to re-run).
-- =====================================================================

-- 1) Question bank: stable code (so this seed can be re-run) + category
alter table public.assessment_questions add column if not exists code text;
alter table public.assessment_questions add column if not exists category text;   -- 'technical' | 'non_technical'
create unique index if not exists uq_assessment_questions_code on public.assessment_questions(code);

-- 2) Attempts: per-attempt option order (needed for correct grading of shuffled
--    options) + integrity results
alter table public.assessment_attempts add column if not exists option_orders jsonb;
alter table public.assessment_attempts add column if not exists risk_score int not null default 0;
alter table public.assessment_attempts add column if not exists integrity_status text;   -- 'clean' | 'review' | 'disqualified'
alter table public.assessment_attempts add column if not exists integrity_notes jsonb;

-- 3) Seed: 50 hard questions (25 technical + 25 non-technical)
insert into public.assessment_questions (code, category, topic, difficulty, question_text, options, correct_index)
values
  ('SCH-T01', 'technical', 'programming', 'hard', 'What is printed by the following Python code?
<pre>def add(x, lst=[]):
    lst.append(x)
    return lst

print(add(1))
print(add(2))
print(add(3, []))</pre>', '["[1], then [1, 2], then [3]", "[1], then [2], then [3]", "[1], then [1, 2], then [1, 2, 3]", "[1], then [2], then [1, 2, 3]"]'::jsonb, 0),
  ('SCH-T02', 'technical', 'programming', 'hard', 'What does this JavaScript snippet log, in order?
<pre>for (var i = 0; i &lt; 3; i++) { setTimeout(() =&gt; console.log(i), 0); }
for (let j = 0; j &lt; 3; j++) { setTimeout(() =&gt; console.log(j), 0); }</pre>', '["3 3 3 3 3 3", "0 1 2 0 1 2", "3 3 3 0 1 2", "0 1 2 3 3 3"]'::jsonb, 2),
  ('SCH-T03', 'technical', 'programming', 'hard', 'After the following Python code runs, what are the values of a, b and c?
<pre>a = [1, 2, 3]
b = a
b += [4]
c = a + [5]</pre>', '["a = [1, 2, 3, 4], b = [1, 2, 3, 4], c = [1, 2, 3, 4, 5]", "a = [1, 2, 3, 4], b = [1, 2, 3, 4], c = [1, 2, 3, 5]", "a = [1, 2, 3], b = [1, 2, 3, 4], c = [1, 2, 3, 4, 5]", "a = [1, 2, 3], b = [1, 2, 3, 4], c = [1, 2, 3, 5]"]'::jsonb, 0),
  ('SCH-T04', 'technical', 'programming', 'hard', 'What does <code>print(7 // -2, -7 % 3, round(2.5))</code> output in Python 3?', '["-3 -1 3", "-3 2 2", "-4 2 2", "-4 -1 3"]'::jsonb, 2),
  ('SCH-T05', 'technical', 'programming', 'hard', 'For the function below, what is the value of <code>g(5)</code>?
<pre>def g(n):
    if n &lt;= 1:
        return 1
    return g(n - 1) + g(n - 2) + 1</pre>', '["15", "13", "9", "11"]'::jsonb, 0),
  ('SCH-T06', 'technical', 'data_structures', 'hard', 'What is the time complexity of this pseudocode as a function of n?
<pre>for (i = n; i &gt;= 1; i = i / 2)
    for (j = 1; j &lt;= i; j++)
        work()</pre>', '["O(n)", "O(n²)", "O(n log n)", "O(log n)"]'::jsonb, 0),
  ('SCH-T07', 'technical', 'data_structures', 'hard', 'Keys 50, 30, 70, 20, 40, 60, 80, 35 are inserted, in that order, into an initially empty binary search tree. What is the post-order traversal of the resulting tree?', '["20, 35, 30, 40, 60, 80, 70, 50", "20, 35, 40, 30, 60, 80, 70, 50", "50, 30, 20, 40, 35, 70, 60, 80", "20, 30, 35, 40, 50, 60, 70, 80"]'::jsonb, 1),
  ('SCH-T08', 'technical', 'data_structures', 'hard', 'Keys 10, 4, 15, 2, 8 are inserted one by one into an empty binary min-heap stored as an array (standard sift-up). The minimum is then removed with a standard extract-min. What does the array look like afterwards?', '["[4, 8, 15, 10]", "[4, 10, 15, 8]", "[4, 8, 10, 15]", "[8, 4, 15, 10]"]'::jsonb, 0),
  ('SCH-T09', 'technical', 'data_structures', 'hard', 'Evaluate the postfix expression: <code>5 6 2 + * 12 4 / -</code>', '["40", "34", "37", "29"]'::jsonb, 2),
  ('SCH-T10', 'technical', 'data_structures', 'hard', 'An undirected weighted graph has these edges: A–B: 4, A–C: 2, B–C: 1, B–D: 5, C–D: 8, C–E: 10, D–E: 2, D–F: 6, E–F: 3. What is the length of the shortest path from A to F?', '["16", "13", "14", "15"]'::jsonb, 1),
  ('SCH-T11', 'technical', 'databases', 'hard', 'A table <code>employees(id, dept, salary)</code> is queried as follows. What does the query return?
<pre>SELECT dept, COUNT(*)
FROM employees
WHERE salary &gt; 50000
GROUP BY dept
HAVING COUNT(*) &gt; 2;</pre>', '["Every employee earning above 50000 whose department has more than two staff", "Departments with more than two employees in total, counting only those who earn above 50000", "The total salary of each department that has more than two employees", "Departments in which more than two employees earn above 50000, with the number of such employees"]'::jsonb, 3),
  ('SCH-T12', 'technical', 'databases', 'hard', 'Table <code>t</code> has a column <code>x</code> holding the four values 1, 2, 3 and NULL (one per row). How many rows does <code>SELECT * FROM t WHERE x NOT IN (1, NULL);</code> return?', '["0", "2", "3", "1"]'::jsonb, 0),
  ('SCH-T13', 'technical', 'databases', 'hard', 'Table A contains the ids {1, 2, 3, 4} and table B contains the ids {3, 4, 5, 6}, all unique. How many rows does <code>A FULL OUTER JOIN B ON A.id = B.id</code> return?', '["8", "4", "6", "2"]'::jsonb, 2),
  ('SCH-T14', 'technical', 'databases', 'hard', 'Transaction T1 reads a row''s balance twice. Between the two reads, T2 updates that row and commits, so T1''s second read returns a different value. Which anomaly occurred?', '["Dirty read", "Phantom read", "Non-repeatable read", "Lost update"]'::jsonb, 2),
  ('SCH-T15', 'technical', 'networking', 'hard', 'Which HTTP method is defined as idempotent but NOT safe?', '["HEAD", "GET", "PUT", "POST"]'::jsonb, 2),
  ('SCH-T16', 'technical', 'networking', 'hard', 'How many usable host addresses does the subnet 192.168.10.0/26 provide?', '["64", "62", "126", "30"]'::jsonb, 1),
  ('SCH-T17', 'technical', 'networking', 'hard', 'In which situation will a browser send a CORS preflight (OPTIONS) request before the actual request?', '["A cross-origin fetch that sends the header Content-Type: application/json", "Any request made over HTTPS", "A same-origin GET request for a JSON file", "A cross-origin GET request with no custom headers"]'::jsonb, 0),
  ('SCH-T18', 'technical', 'operating_systems', 'hard', 'Which of the following is NOT one of the four necessary (Coffman) conditions for a deadlock?', '["Mutual exclusion", "Hold and wait", "Resource preemption", "Circular wait"]'::jsonb, 2),
  ('SCH-T19', 'technical', 'operating_systems', 'hard', 'A process references pages in the order 1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5. With FIFO page replacement and 4 initially empty frames, how many page faults occur?', '["7", "8", "10", "9"]'::jsonb, 2),
  ('SCH-T20', 'technical', 'operating_systems', 'hard', 'Processes P1, P2, P3 and P4 arrive at t = 0, 1, 2 and 3 ms with CPU bursts of 8, 4, 9 and 5 ms. Using preemptive Shortest Remaining Time First (SRTF) scheduling, what is the average waiting time?', '["5.5 ms", "8.75 ms", "6.5 ms", "7.75 ms"]'::jsonb, 2),
  ('SCH-T21', 'technical', 'ai_data', 'hard', 'A neural network reaches 99% accuracy on its training data but only 72% on validation data. Which action is most likely to help?', '["Add more layers and train for more epochs", "Evaluate only on the training set from now on", "Apply regularisation (such as dropout or weight decay), add more training data, or use early stopping", "Remove the validation set to reduce noise"]'::jsonb, 2),
  ('SCH-T22', 'technical', 'ai_data', 'hard', 'A classifier is evaluated on 1,000 samples with TP = 40, FP = 10, FN = 20 and TN = 930. What is its F1-score, to two decimal places?', '["0.73", "0.67", "0.97", "0.80"]'::jsonb, 0),
  ('SCH-T23', 'technical', 'ai_data', 'hard', 'A data scientist standardises an entire dataset (zero mean, unit variance) using its overall mean and standard deviation, and only then splits it into training and test sets. What is the main problem with this approach?', '["Multicollinearity between the features", "Data leakage: information from the test set influenced the scaling applied to the training data", "Class imbalance between the two splits", "Underfitting caused by standardisation"]'::jsonb, 1),
  ('SCH-T24', 'technical', 'security_cloud', 'hard', 'A web page renders user comments directly into its HTML. What is the most reliable primary defence against stored cross-site scripting (XSS)?', '["Serving the site over HTTPS", "Disabling right-click on the page", "Contextual output encoding of user data at the point it is rendered", "Rejecting comments that contain the word \"script\""]'::jsonb, 2),
  ('SCH-T25', 'technical', 'security_cloud', 'hard', 'What is a genuine advantage of horizontal scaling over vertical scaling for a web service?', '["Capacity grows by adding machines, so there is no single-machine ceiling and a failed node need not take the service down", "The application never needs any changes to run on multiple machines", "Keeping data consistent becomes simpler than on a single server", "Network latency between components always decreases"]'::jsonb, 0),
  ('SCH-N01', 'non_technical', 'quantitative', 'hard', 'Two trains, 150 m and 200 m long, run on parallel tracks in opposite directions at 54 km/h and 36 km/h. How many seconds do they take to cross each other completely?', '["18 seconds", "14 seconds", "16 seconds", "12 seconds"]'::jsonb, 1),
  ('SCH-N02', 'non_technical', 'quantitative', 'hard', 'A can finish a job in 12 days and B in 18 days. They work together for 4 days, then A leaves and B completes the remaining work alone. In how many days in total is the job finished?', '["14 days", "10 days", "13 days", "12 days"]'::jsonb, 3),
  ('SCH-N03', 'non_technical', 'quantitative', 'hard', 'What is the difference between the compound interest (compounded annually) and the simple interest on ₹10,000 at 10% per annum for 3 years?', '["₹310", "₹100", "₹331", "₹300"]'::jsonb, 0),
  ('SCH-N04', 'non_technical', 'quantitative', 'hard', 'A bag holds 5 red, 4 blue and 3 green balls. Three balls are drawn at random without replacement. What is the probability that all three are of different colours?', '["1/4", "3/11", "5/22", "2/9"]'::jsonb, 1),
  ('SCH-N05', 'non_technical', 'quantitative', 'hard', '40 kg of an alloy containing 30% silver is melted with x kg of another alloy containing 50% silver to get an alloy with 42% silver. What is x?', '["40 kg", "50 kg", "80 kg", "60 kg"]'::jsonb, 3),
  ('SCH-N06', 'non_technical', 'quantitative', 'hard', 'A shopkeeper marks an article 40% above its cost price and then allows successive discounts of 10% and 5%. What is his profit percentage?', '["21%", "19.7%", "17.5%", "25%"]'::jsonb, 1),
  ('SCH-N07', 'non_technical', 'logical_reasoning', 'hard', 'Find the next term in the series: 3, 7, 16, 35, 74, ?', '["157", "149", "148", "153"]'::jsonb, 3),
  ('SCH-N08', 'non_technical', 'logical_reasoning', 'hard', 'Six friends P, Q, R, S, T and U sit in a row facing north. Q sits third from the left and P sits immediately to the right of Q. T sits somewhere to the left of Q but not at either end. S sits at the extreme right end. R and U do not sit next to each other, while T and U do sit next to each other. Who sits at the extreme left end?', '["U", "P", "T", "R"]'::jsonb, 0),
  ('SCH-N09', 'non_technical', 'logical_reasoning', 'hard', 'Statements: All engineers are analysts. Some analysts are managers. No manager is a designer.
Conclusions:
I. Some engineers are managers.
II. Some analysts are not designers.
III. No engineer is a designer.
Which conclusion(s) definitely follow?', '["II and III follow", "Only I follows", "Only II follows", "I and II follow"]'::jsonb, 2),
  ('SCH-N10', 'non_technical', 'logical_reasoning', 'hard', 'Meera starts facing north. She walks 3 km, turns right and walks 3 km, turns right again and walks 11 km, then turns left and walks 3 km. How far, and in which direction, is she from her starting point?', '["8 km, south-east", "10 km, south-east", "12 km, north-east", "10 km, south-west"]'::jsonb, 1),
  ('SCH-N11', 'non_technical', 'logical_reasoning', 'hard', 'On an island every person is either a truth-teller (always tells the truth) or a liar (always lies). A says: "B is a liar." B says: "A and C are the same type." C says: "A is a liar." Who are the liars?', '["A and B", "Only C", "B and C", "A and C"]'::jsonb, 2),
  ('SCH-N12', 'non_technical', 'data_interpretation', 'hard', 'Quarterly revenue (₹ crore):
Company X: Q1 120, Q2 150, Q3 135, Q4 180
Company Y: Q1 100, Q2 130, Q3 160, Q4 170
By what percentage, to one decimal place, does X''s annual revenue exceed Y''s?', '["4.3%", "5.0%", "9.0%", "4.5%"]'::jsonb, 3),
  ('SCH-N13', 'non_technical', 'data_interpretation', 'hard', 'A firm''s monthly expenses total ₹4,80,000, split as Salaries 40%, Rent 25%, Marketing 15%, Utilities 8% and Miscellaneous 12%. If the marketing budget is raised by 20% and the salary bill is cut by 10%, with everything else unchanged, what is the new monthly total?', '["₹4,80,000", "₹4,84,800", "₹4,75,200", "₹4,68,000"]'::jsonb, 2),
  ('SCH-N14', 'non_technical', 'data_interpretation', 'hard', 'Batch A has 30 students with an average score of 72. Batch B has 20 students averaging 60. Five students from Batch A, whose own average score is 80, are moved to Batch B. What is the new average score of Batch A?', '["72", "71.2", "69.6", "70.4"]'::jsonb, 3),
  ('SCH-N15', 'non_technical', 'verbal', 'hard', 'Which of the following sentences is grammatically correct?', '["Each of the reports have been reviewed by the auditor.", "Neither of the two candidates is willing to relocate.", "The number of applicants have increased significantly this year.", "One of the reasons for the delay were the vendor''s errors."]'::jsonb, 1),
  ('SCH-N16', 'non_technical', 'verbal', 'hard', 'A company reports that productivity rose 12% in the six months after it introduced flexible working hours, and concludes that flexible hours caused the increase. Which of the following, if true, most weakens this conclusion?', '["In the same six months the company also cut meeting time by a third and adopted new workflow software, both of which independently raise productivity", "Several competitors also offer flexible working hours", "Employees say they prefer flexible working hours", "Productivity had been flat for the previous two years"]'::jsonb, 0),
  ('SCH-N17', 'non_technical', 'verbal', 'hard', 'Read the passage:
"Cities that replaced short-haul flights with high-speed rail saw airport congestion fall, yet total travel emissions fell by less than planners had projected. Analysts noted that cheaper, faster rail service encouraged many residents to take trips they would not previously have made."
Which conclusion is best supported by the passage?', '["Airport congestion did not fall after the switch", "The planners'' projections were unrelated to the rail network", "Part of the emissions saving was offset by extra travel that the new service made attractive", "High-speed rail produces more emissions than short-haul flights"]'::jsonb, 2),
  ('SCH-N18', 'non_technical', 'verbal', 'hard', 'Ephemeral : Permanent :: Frugal : ?', '["Miserly", "Extravagant", "Prudent", "Thrifty"]'::jsonb, 1),
  ('SCH-N19', 'non_technical', 'business_finance', 'hard', 'A product has fixed costs of ₹6,00,000 a year, sells for ₹250 per unit and has a variable cost of ₹150 per unit. How many units must be sold in a year to earn a profit of ₹1,50,000?', '["6,500 units", "6,000 units", "9,000 units", "7,500 units"]'::jsonb, 3),
  ('SCH-N20', 'non_technical', 'business_finance', 'hard', 'Which of these offers the highest effective annual rate of return?', '["12.6% per annum compounded annually", "12.5% per annum compounded annually", "12.2% per annum compounded quarterly", "12% per annum compounded monthly"]'::jsonb, 2),
  ('SCH-N21', 'non_technical', 'business_finance', 'hard', 'A subscription business spends ₹2,000 to acquire each customer (CAC). A customer pays ₹500 a month, the gross margin is 60%, and the average customer stays 20 months. What is the LTV to CAC ratio (LTV measured on gross margin)?', '["5.0", "3.0", "6.0", "1.5"]'::jsonb, 1),
  ('SCH-N22', 'non_technical', 'situational_judgement', 'hard', 'You realise that the module you delivered yesterday has a bug, and a client demo that uses it starts in two hours. Your manager is in a meeting. What is the best course of action?', '["Message your manager now with the issue, its impact and your proposed fix or workaround, then start fixing it", "Wait until the meeting ends so you do not interrupt", "Postpone the demo yourself without telling anyone", "Quietly patch it and mention it only if someone notices"]'::jsonb, 0),
  ('SCH-N23', 'non_technical', 'situational_judgement', 'hard', 'In a review meeting a colleague presents, as their own, an analysis that you built. What is the best first step?', '["Tell other teammates about it informally", "Speak to them privately soon afterwards, describe what you observed and ask them to set the credit right; involve your manager only if it continues", "Say nothing and stop sharing your work with them", "Correct them publicly in the meeting so the record is clear"]'::jsonb, 1),
  ('SCH-N24', 'non_technical', 'situational_judgement', 'hard', 'After you shortlist a vendor''s proposal, their representative sends you a personal gift voucher "as a thank you". What should you do?', '["Accept it and donate the value to charity without telling anyone", "Keep it quietly but avoid working on that vendor''s proposal again", "Politely decline or return it, and inform your manager or compliance contact in line with company policy", "Accept it, since the shortlisting is already done"]'::jsonb, 2),
  ('SCH-N25', 'non_technical', 'situational_judgement', 'hard', 'Two senior stakeholders each ask you for an urgent deliverable, and you cannot complete both by the same deadline. What is the best approach?', '["Do the easier request first because it can be finished quickly", "Split your time equally and hope both are acceptable", "Tell both of them (or your common manager) about the conflict, share the time trade-offs, and ask them to agree the priority", "Do whichever request came from the more senior person and say nothing to the other"]'::jsonb, 2)
on conflict (code) do update set
  category      = excluded.category,
  topic         = excluded.topic,
  difficulty    = excluded.difficulty,
  question_text = excluded.question_text,
  options       = excluded.options,
  correct_index = excluded.correct_index;
