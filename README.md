# GGTH-Predictions-2026
A machine learning system that predicts forex price movements using an ensemble of AI models and provides a Metatrader 5 Expert Advisor the data it needs to make trades.

To install simply run the setup file and follow the instructions.

<stromg>ATTENTION - In settings for the expert advisor TURN STRATEGY TESTER MODE TO FALSE TO SEE THE PREDICTIONS DISPLAYED ON YOUR CHART!!!! </strong>

IMPORTANT - for the system to work properly you need to be logged into the community portal on your Metatrader 5 platform: Click TOOLS - OPTIONS - COMMUNITY - then login.

the AI models can be trained on any Forex pair you desire. I would suggest you backtest any new forex pairs and settings before using. To backtest you need to run the Generate backtest to create a file that will contain what prices AI would have predicted in that timeframe. Then it can use those predictions during the strategy tester run.

<strong>IMPORTANT!!!!!!!!!!!!!!!!!!!!!</strong>
When backtesting to keep the AI from cheating you MUST train it on a different dates then your prediction file for backtesting for example train the AI on dates 2019-01-01 to 2023-12-31 then create a backtesting prediction file for 2024-01-01 to 2026-2-22
Then run your strategy tester for the timeframe your backtest prediction files were created on.
All of this can be done easily through the User interface.

Good Luck!!
